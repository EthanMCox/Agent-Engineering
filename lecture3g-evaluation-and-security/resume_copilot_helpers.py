import json
from typing import Any

def build_candidate_choices(
    truth: dict[str, dict[str, Any]],
) -> tuple[list[str], dict[str, str]]:
    labels: list[str] = []
    label_to_key: dict[str, str] = {}

    for file_key, record in truth.items():
        name = (record.get("full_name") or "").strip() or "(Unnamed Candidate)"
        label = f"{name} — {file_key}"
        labels.append(label)
        label_to_key[label] = file_key

    labels.sort()
    return labels, label_to_key


def _current_role(record: dict[str, Any]) -> str:
    title = (record.get("job_title") or "").strip()
    employers = record.get("employers") or []
    employer = employers[0].strip() if employers and employers[0] else ""

    if title and employer:
        return f"{title} at {employer}"
    if title:
        return title
    if employer:
        return f"Professional at {employer}"
    return "Professional"


def _years_experience_string(record: dict[str, Any]) -> str:
    value = record.get("years_experience")
    try:
        years = float(value)
    except (TypeError, ValueError):
        return ""

    rounded = round(years)
    if abs(years - rounded) < 1e-6:
        return str(int(rounded))
    return f"{years:.1f}"


def build_candidate_context(
    candidate_label: str,
    recruiter_notes: str,
    truth: dict[str, dict[str, Any]],
    label_to_key: dict[str, str],
) -> str:
    file_key = label_to_key.get(candidate_label)
    if not file_key:
        raise ValueError("Invalid candidate selection.")

    record = truth[file_key]
    payload = {
        "file_key": file_key,
        "candidate_label": candidate_label,
        "structured_resume_fields": {
            "full_name": (record.get("full_name") or "").strip(),
            "years_experience": _years_experience_string(record),
            "current_role": _current_role(record),
            "job_title": (record.get("job_title") or "").strip(),
            "employers": record.get("employers") or [],
        },
        "gold_talking_points": {
            "name": (record.get("full_name") or "").strip(),
            "yoe": _years_experience_string(record),
            "role": _current_role(record),
            "notes": (recruiter_notes or "").strip(),
        },
        "recruiter_notes": (recruiter_notes or "").strip(),
    }
    return json.dumps(payload, ensure_ascii=False)
