import base64
import json
import re
from typing import Any

from app_helpers import RESUMES_DIR, parse_json_object
from pdf2text import pdf_text_or_ocr


FIELDS = [
    "full_name",
    "phone_number",
    "highest_degree",
    "field_of_study",
    "institution",
    "graduation_year",
    "job_title",
    "years_experience",
    "employers",
]
SCHEMA_HINT = {
    "full_name": "",
    "phone_number": "",
    "highest_degree": "",
    "field_of_study": "",
    "institution": "",
    "graduation_year": "",
    "job_title": "",
    "years_experience": "",
    "employers": [],
}
INSTITUTION_STOP = {"university", "college", "institute", "school", "of", "the", "and", "for"}
EMPLOYER_STOP = {"inc", "llc", "ltd", "co", "corp", "corporation", "group", "company", "holdings",
                 "technologies", "technology", "solutions", "services", "systems"}
DEG_MAP = {
    "bs": "BS", "bsc": "BS", "bachelor of science": "BS",
    "ba": "BA", "bachelor of arts": "BA",
    "beng": "BS", "be": "BS",
    "barch": "BArch",
    "bba": "BBA",
    "ms": "MS", "msc": "MS", "master of science": "MS",
    "ma": "MA", "master of arts": "MA",
    "mba": "MBA",
    "emba": "EMBA",
    "phd": "PhD", "doctor of philosophy": "PhD",
    "mca": "MCA",
    "aa": "AA", "associate of arts": "AA",
    "as": "AS", "associate of science": "AS",
    "aas": "AAS", "associate of applied science": "AAS",
    "aa-s": "AS",
}
WEIGHTS = {
    "full_name": 0.15,
    "phone_number": 0.15,
    "highest_degree": 0.10,
    "field_of_study": 0.10,
    "institution": 0.10,
    "graduation_year": 0.08,
    "job_title": 0.10,
    "years_experience": 0.07,
    "employers": 0.15,
}
DEFAULT_PROMPT_TEMPLATE = (
    "File: <<file_name>>\n\n"
    "Extract the fields using this JSON schema. Return only JSON.\n"
    f"Schema example: {json.dumps(SCHEMA_HINT)}\n\n"
    "Resume text begins below:\n---\n"
    "<<resume_text>>\n---\n"
)


def _normalize_prediction(data: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for field in FIELDS:
        default_value: Any = [] if field == "employers" else ""
        value = data.get(field, default_value)
        if field == "employers":
            normalized[field] = value if isinstance(value, list) else []
        else:
            normalized[field] = "" if value is None else str(value)
    return normalized


def extract_resume_context(file_name: str) -> str:
    path = RESUMES_DIR / file_name
    result = pdf_text_or_ocr(str(path))
    payload = {
        "file_name": file_name,
        "resume_text": result.text,
        "ocr_metadata": {
            "used_ocr": result.used_ocr,
            "page_count": result.page_count,
            "ocr_pages": result.ocr_pages,
            "warnings": result.warnings,
        },
        "schema_hint": SCHEMA_HINT,
    }
    return json.dumps(payload, ensure_ascii=False)


def score_prediction(prediction: dict[str, Any], truth_record: dict[str, Any]) -> dict[str, Any]:
    return _compute_extraction_score(_normalize_prediction(prediction), truth_record)


def _compute_extraction_score(pred: dict[str, Any], truth: dict[str, Any]) -> dict[str, Any]:
    def norm_empty(value) -> str:
        if value is None:
            return ""
        text = str(value).strip().lower()
        if text in {"n/a", "na", "none", "null", "not specified", "not listed", "unknown", ""}:
            return ""
        return text

    def norm_spaces(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    def strip_punct(text: str) -> str:
        return re.sub(r"[^\w\s]", " ", text)

    def tokens(text: str) -> list[str]:
        text = norm_spaces(strip_punct(text.lower()))
        return text.split() if text else []

    def jaccard(a: str, b: str, stop: set = None) -> float:
        set_a = set(tokens(a))
        set_b = set(tokens(b))
        if stop:
            set_a = {token for token in set_a if token not in stop}
            set_b = {token for token in set_b if token not in stop}
        if not set_a and not set_b:
            return 1.0
        if not set_a or not set_b:
            return 0.0
        return len(set_a & set_b) / len(set_a | set_b)

    def norm_phone(text: str) -> str:
        return re.sub(r"\D", "", norm_empty(text))

    def norm_degree(text: str) -> str:
        text = norm_empty(text)
        if not text:
            return ""
        text = text.replace(".", "").strip().lower()
        text = re.sub(r"\bdegree\b", "", text).strip()
        return DEG_MAP.get(text, text.upper())

    def bool_comparison(pred_value: str, truth_value: str) -> float:
        if not pred_value and not truth_value:
            return 1.0
        if not pred_value or not truth_value:
            return 0.0
        return 1.0 if pred_value == truth_value else 0.0

    def parse_year(text: str) -> str:
        text = norm_empty(text)
        if not text:
            return ""
        match = re.search(r"-?\d{1,4}", text)
        return match.group(0) if match else ""

    def parse_float(value: Any):
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = norm_empty(str(value))
        if not text:
            return None
        try:
            return float(text)
        except Exception:
            match = re.search(r"-?\d+(\.\d+)?", text)
            return float(match.group(0)) if match else None

    def score_years_experience(pred_value: Any, truth_value: Any) -> float:
        pred_num = parse_float(pred_value)
        truth_num = parse_float(truth_value)
        if pred_num is None and truth_num is None:
            return 1.0
        if pred_num is None or truth_num is None:
            return 0.0
        diff = abs(pred_num - truth_num)
        if diff <= 1.0:
            return 1.0
        denom = abs(truth_num) if abs(truth_num) > 0.0 else 1.0
        return max(0.0, 1.0 - (diff / denom))

    def norm_entity(text: str, stopset: set) -> str:
        return " ".join(token for token in tokens(text) if token not in stopset)

    def score_employers(pred_list: list[str], truth_list: list[str], gap_penalty: float = 0.0) -> float:
        norm_pred = [norm_entity(item, EMPLOYER_STOP) for item in (pred_list or [])]
        norm_truth = [norm_entity(item, EMPLOYER_STOP) for item in (truth_list or [])]
        m, n = len(norm_pred), len(norm_truth)
        if m == 0 and n == 0:
            return 1.0

        dp = [[0.0] * (n + 1) for _ in range(m + 1)]
        gap_ct = [[0] * (n + 1) for _ in range(m + 1)]

        for i in range(1, m + 1):
            dp[i][0] = dp[i - 1][0] + gap_penalty
            gap_ct[i][0] = gap_ct[i - 1][0] + 1
        for j in range(1, n + 1):
            dp[0][j] = dp[0][j - 1] + gap_penalty
            gap_ct[0][j] = gap_ct[0][j - 1] + 1

        for i in range(1, m + 1):
            for j in range(1, n + 1):
                sim = jaccard(norm_pred[i - 1], norm_truth[j - 1])
                cand_up = (dp[i - 1][j] + gap_penalty, gap_ct[i - 1][j] + 1)
                cand_left = (dp[i][j - 1] + gap_penalty, gap_ct[i][j - 1] + 1)
                cand_diag = (dp[i - 1][j - 1] + sim, gap_ct[i - 1][j - 1])
                best = max([cand_up, cand_left, cand_diag], key=lambda item: (item[0], -item[1]))
                dp[i][j], gap_ct[i][j] = best

        return max(0.0, min(1.0, dp[m][n] / max(m, n, 1)))

    scores = {
        "full_name": jaccard(pred.get("full_name", ""), truth.get("full_name", "")),
        "phone_number": bool_comparison(norm_phone(pred.get("phone_number", "")), norm_phone(truth.get("phone_number", ""))),
        "highest_degree": bool_comparison(norm_degree(pred.get("highest_degree", "")), norm_degree(truth.get("highest_degree", ""))),
        "field_of_study": jaccard(pred.get("field_of_study", ""), truth.get("field_of_study", "")),
        "institution": jaccard(pred.get("institution", ""), truth.get("institution", ""), stop=INSTITUTION_STOP),
        "graduation_year": bool_comparison(parse_year(pred.get("graduation_year", "")), parse_year(truth.get("graduation_year", ""))),
        "job_title": jaccard(pred.get("job_title", ""), truth.get("job_title", "")),
        "years_experience": score_years_experience(pred.get("years_experience", ""), truth.get("years_experience", "")),
        "employers": score_employers(pred.get("employers", []), truth.get("employers", [])),
    }

    total = 0.0
    for key, weight in WEIGHTS.items():
        total += weight * scores[key]
    scores["total"] = max(0.0, min(1.0, total))
    return scores


def _format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def make_scores_matrix_html(
    selected_files: list[str],
    scores_by_file: dict[str, dict[str, float]],
) -> str:
    if not selected_files:
        return "<p>Select files and click Compute Results to see the field score matrix.</p>"

    ordered_files = sorted(selected_files)

    def avg_for_field(field: str) -> float:
        total = sum(scores_by_file.get(file_name, {}).get(field, 0.0) for file_name in ordered_files)
        return total / len(ordered_files)

    html = [
        '<div style="overflow-x:auto">',
        '<table border="1" cellpadding="4" cellspacing="0">',
        "<tr><th>Field</th><th>Average</th>" + "".join(f"<th>{file_name}</th>" for file_name in ordered_files) + "</tr>",
    ]
    for field in FIELDS + ["total"]:
        html.append("<tr>")
        html.append(f"<td>{field}</td>")
        average = avg_for_field(field)
        if field == "total":
            html.append(f'<td style="background:#f0f0f0;font-weight:bold">{average:.3f}</td>')
        else:
            html.append(f"<td>{average:.3f}</td>")
        for file_name in ordered_files:
            score = scores_by_file.get(file_name, {}).get(field, 0.0)
            html.append(f"<td>{score:.3f}</td>")
        html.append("</tr>")
    html.extend(["</table>", "</div>"])
    return "\n".join(html)


def make_truth_comparison_html(
    file_name: str | None,
    prediction: dict[str, Any],
    truth: dict[str, dict[str, Any]],
) -> str:
    if not file_name:
        return "<p>Select a file to view extracted and truth values.</p>"

    truth_record = truth.get(file_name, {})
    html = [
        '<div style="overflow-x:auto">',
        '<table border="1" cellpadding="4" cellspacing="0">',
        "<tr><th>Field</th><th>Extracted</th><th>Truth</th></tr>",
    ]
    for field in FIELDS:
        html.append(
            f"<tr><td>{field}</td><td>{_format_value(prediction.get(field, ''))}</td>"
            f"<td>{_format_value(truth_record.get(field, ''))}</td></tr>"
        )
    html.extend(["</table>", "</div>"])
    return "\n".join(html)


def make_pdf_html(file_name: str | None) -> str:
    if not file_name:
        return "<p>No resume selected.</p>"

    pdf_path = RESUMES_DIR / file_name
    if not pdf_path.exists():
        return "<p>No resume selected.</p>"

    try:
        encoded = base64.b64encode(pdf_path.read_bytes()).decode()
    except OSError:
        return "<p>PDF preview unavailable.</p>"

    return (
        '<iframe src="data:application/pdf;base64,'
        + encoded
        + '" style="width:100%;height:600px;border:none;"></iframe>'
    )


def parse_extraction_response(text: str) -> dict[str, Any]:
    return _normalize_prediction(parse_json_object(text))
