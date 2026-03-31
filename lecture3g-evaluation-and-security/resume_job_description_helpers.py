import re
from textwrap import dedent
from typing import Any


COMPANY_OVERVIEW = (
    "Acme, Inc. is the leader in software for managing widget inventory and sales. "
    "From startups to Fortune 500 companies, we are your go-to solution for widget management. "
    "Our platform helps teams track stock, automate reorders, and analyze performance at scale. "
    "'The world's widgets. Our intelligence.'"
)
SECTION_PATTERNS = {
    "Job Title": r"(?mi)^\s*Job\s*Title\s*:",
    "Company Overview": r"(?mi)^\s*Company\s*Overview\s*$",
    "Duties & Responsibilities": r"(?mi)^\s*Duties\s*&\s*Responsibilities\s*$",
    "Required Qualifications": r"(?mi)^\s*Required\s*Qualifications\s*$",
    "Preferred Qualifications": r"(?mi)^\s*Preferred\s*Qualifications\s*$",
    "Benefits": r"(?mi)^\s*Benefits\s*$",
    "Salary Range": r"(?mi)^\s*Salary\s*Range\s*$",
    "Job Conditions": r"(?mi)^\s*Job\s*Conditions\s*$",
}
DEFAULT_GEN_PROMPT = dedent(
    f"""
    You are an expert HR writer for Acme, Inc. Write a professional Job Description for the given title.
    Include these labeled sections exactly once and in this order:

    Job Title: <exact title>
    Company Overview
    Duties & Responsibilities
    Required Qualifications
    Preferred Qualifications
    Benefits
    Salary Range
    Job Conditions

    Use concise bullets under duties and qualifications. Keep it under ~400 words.
    Company overview must accurately reflect our corporate overview:
    "{COMPANY_OVERVIEW}"
    """
).strip()
JOB_TITLES = [
    "Senior Engineering Manager",
    "Junior Software Engineer",
    "Product Manager, Inventory Platform",
    "Data Analyst, Sales & Inventory",
    "Solutions Engineer (B2B SaaS)",
    "Customer Success Manager, Enterprise",
]
_SECTION_ORDER = [
    "Company Overview",
    "Duties & Responsibilities",
    "Required Qualifications",
    "Preferred Qualifications",
    "Benefits",
    "Salary Range",
    "Job Conditions",
]
_BULLET_PATTERN = re.compile(r"^\s*(?:[-*•]|\d+\.)\s+")


def _has_section(text: str, label: str) -> bool:
    return re.search(SECTION_PATTERNS[label], text) is not None


def _bullet_count_after(text: str, section_label: str, max_lines: int = 60) -> int:
    block = _extract_section_block(text, section_label)
    if not block:
        return 0
    return sum(1 for line in block.splitlines()[:max_lines] if _BULLET_PATTERN.match(line))


def _has_salary_range(text: str) -> bool:
    return re.search(r"\$\s?\d[\d,]*(?:\.\d{2})?\s*-\s*\$\s?\d[\d,]*(?:\.\d{2})?", text) is not None


def _normalize_chars(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _levenshtein_similarity(a: str, b: str) -> float:
    norm_a = _normalize_chars(a)
    norm_b = _normalize_chars(b)
    n, m = len(norm_a), len(norm_b)
    if n == 0:
        return float(m == 0)
    if m == 0:
        return 0.0
    if n > m:
        norm_a, norm_b = norm_b, norm_a
        n, m = m, n

    prev = list(range(n + 1))
    for j in range(1, m + 1):
        curr = [j] + [0] * n
        bj = norm_b[j - 1]
        for i in range(1, n + 1):
            cost = 0 if norm_a[i - 1] == bj else 1
            curr[i] = min(
                prev[i] + 1,
                curr[i - 1] + 1,
                prev[i - 1] + cost,
            )
        prev = curr

    return max(0.0, 1.0 - prev[n] / max(len(norm_a), len(norm_b)))


def _extract_section_block(text: str, label: str) -> str:
    if label not in SECTION_PATTERNS:
        return ""

    lines = text.splitlines()
    start_index = None
    for index, line in enumerate(lines):
        if re.match(SECTION_PATTERNS[label], line):
            start_index = index + 1
            break

    if start_index is None:
        return ""

    collected: list[str] = []
    for line in lines[start_index:]:
        if any(
            other_label != label and re.match(SECTION_PATTERNS[other_label], line)
            for other_label in _SECTION_ORDER
        ):
            break
        collected.append(line)

    return "\n".join(collected).strip()


def _extract_job_title(text: str) -> str:
    match = re.search(r"(?mi)^\s*Job\s*Title\s*:\s*(.*)$", text)
    return match.group(1).strip() if match else ""


def _infer_level_from_title(title: str) -> str:
    lowered = title.lower()
    if "junior" in lowered:
        return "junior"
    if "senior" in lowered or "sr." in lowered or re.search(r"\bsr\b", lowered):
        return "senior"
    return ""


def _parse_years_experience(text_block: str) -> int | None:
    years = []
    for match in re.finditer(r"(\d+)\s*\+?\s*(?:years?|yrs?)", text_block or "", flags=re.IGNORECASE):
        years.append(int(match.group(1)))
    return max(years) if years else None


def _parse_salary_range(block: str) -> tuple[int | None, int | None]:
    values: list[int] = []
    for match in re.finditer(r"\$?\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)\s*([kK])?", block or ""):
        value = int(match.group(1).replace(",", ""))
        if match.group(2):
            value *= 1000
        values.append(value)
    if not values:
        return None, None
    if "-" in (block or "") and len(values) >= 2:
        low, high = values[0], values[1]
        return (high, low) if low > high else (low, high)
    if len(values) == 1:
        return values[0], None
    return min(values), max(values)


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def _range_score(count: int, low: int = 3, high: int = 6) -> float:
    if low <= count <= high:
        return 1.0
    if count < low:
        # Penalize too-few bullets more harshly than too many.
        return max(0.0, 1.0 - 0.4 * (low - count))
    return max(0.0, 1.0 - 0.2 * (count - high))


def objective_eval(jd_text: str) -> dict[str, Any]:
    checks = {label: _has_section(jd_text, label) for label in SECTION_PATTERNS}
    overview_block = _extract_section_block(jd_text, "Company Overview")
    duties_bullets = _bullet_count_after(jd_text, "Duties & Responsibilities")
    required_bullets = _bullet_count_after(jd_text, "Required Qualifications")
    word_count = _word_count(jd_text)

    required_sections_present = 1.0 if all(checks.values()) else 0.0
    duties_score = _range_score(duties_bullets)
    required_score = _range_score(required_bullets)
    salary_score = 1.0 if _has_salary_range(jd_text) else 0.0
    overview_score = round(_levenshtein_similarity(overview_block, COMPANY_OVERVIEW), 3)
    length_score = 1.0 if word_count <= 300 else max(0.0, 1.0 - 0.1 * ((word_count - 300 + 49) // 50))

    component_scores = {
        "required_sections_present": required_sections_present,
        "duties_bullet_count_score": round(duties_score, 3),
        "required_quals_bullet_count_score": round(required_score, 3),
        "salary_range_present": salary_score,
        "company_overview_match": overview_score,
        "length_within_limit": round(length_score, 3),
    }
    overall = round(sum(component_scores.values()) / len(component_scores), 3)
    return {
        "sections_missing": [label for label, present in checks.items() if not present],
        "bullet_counts": {
            "Duties & Responsibilities": duties_bullets,
            "Required Qualifications": required_bullets,
        },
        "word_count": word_count,
        "objective_scores": component_scores,
        "overall_objective": overall,
    }


def format_objective_report(report: dict[str, Any]) -> str:
    scores = report["objective_scores"]
    bullet_counts = report["bullet_counts"]
    lines = [
        f"Overall objective score: {report['overall_objective']}",
        f"Required sections present: {scores['required_sections_present']}",
        f"Duties bullet count score: {scores['duties_bullet_count_score']} ({bullet_counts['Duties & Responsibilities']} bullets)",
        f"Required qualifications bullet count score: {scores['required_quals_bullet_count_score']} ({bullet_counts['Required Qualifications']} bullets)",
        f"Salary range present: {scores['salary_range_present']}",
        f"Company overview match score: {scores['company_overview_match']}",
        f"Length within limit: {scores['length_within_limit']} ({report['word_count']} words)",
        f"Missing sections: {', '.join(report['sections_missing']) if report['sections_missing'] else 'None'}",
    ]
    return "\n".join(lines)
