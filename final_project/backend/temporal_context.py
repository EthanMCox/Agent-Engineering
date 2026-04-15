from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


DEFAULT_TIMEZONE = "America/Denver"


@dataclass(frozen=True, slots=True)
class TermWindow:
    name: str
    start: date
    end: date


def _safe_timezone(tz_name: str) -> ZoneInfo | None:
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return None


def current_local_date(tz_name: str = DEFAULT_TIMEZONE) -> date:
    tz = _safe_timezone(tz_name)
    if tz is not None:
        return datetime.now(tz).date()
    return datetime.now().astimezone().date()


def parse_reference_date(value: str | None, tz_name: str = DEFAULT_TIMEZONE) -> date:
    if not value:
        return current_local_date(tz_name)
    try:
        return date.fromisoformat(value.strip())
    except Exception:
        return current_local_date(tz_name)


def _byu_term_windows(year: int) -> list[TermWindow]:
    return [
        TermWindow("Winter Semester", date(year, 1, 1), date(year, 4, 30)),
        TermWindow("Spring Term", date(year, 5, 1), date(year, 6, 30)),
        TermWindow("Summer Term", date(year, 7, 1), date(year, 8, 31)),
        TermWindow("Fall Semester", date(year, 9, 1), date(year, 12, 31)),
    ]


def _find_term_for_date(reference_date: date) -> TermWindow:
    for term in _byu_term_windows(reference_date.year):
        if term.start <= reference_date <= term.end:
            return term
    return _byu_term_windows(reference_date.year)[0]


def _next_term(reference_date: date) -> TermWindow:
    windows = _byu_term_windows(reference_date.year) + _byu_term_windows(reference_date.year + 1)
    for term in windows:
        if term.start > reference_date:
            return term
    return windows[0]


def _previous_term(reference_date: date) -> TermWindow:
    windows = _byu_term_windows(reference_date.year - 1) + _byu_term_windows(reference_date.year)
    previous = windows[0]
    for term in windows:
        if term.end < reference_date:
            previous = term
    return previous


def _term_to_dict(term: TermWindow, confidence: str, rationale: str) -> dict[str, str]:
    return {
        "name": term.name,
        "start_date": term.start.isoformat(),
        "end_date": term.end.isoformat(),
        "confidence": confidence,
        "rationale": rationale,
    }


def _timeframe_type(query: str) -> str:
    q = query.lower()
    if any(kw in q for kw in ("next semester", "next term", "upcoming semester", "upcoming term")):
        return "next_term"
    if any(kw in q for kw in ("last semester", "previous semester", "last term", "previous term")):
        return "previous_term"
    if any(kw in q for kw in ("this semester", "this term", "current semester", "current term")):
        return "current_term"
    if any(kw in q for kw in ("today", "tonight", "tomorrow", "this week", "next week", "this month")):
        return "short_horizon"
    return "general"


def infer_timeframe_context(
    *,
    query: str,
    reference_date_value: str | None = None,
    timezone: str = DEFAULT_TIMEZONE,
) -> dict[str, object]:
    reference_date = parse_reference_date(reference_date_value, timezone)
    timeframe_type = _timeframe_type(query)
    current_term = _find_term_for_date(reference_date)
    next_term = _next_term(reference_date)
    previous_term = _previous_term(reference_date)

    primary = current_term
    primary_rationale = "Defaulted to current term for this date."
    if timeframe_type == "next_term":
        primary = next_term
        primary_rationale = "User asked about next/upcoming term."
    elif timeframe_type == "previous_term":
        primary = previous_term
        primary_rationale = "User asked about previous term."

    alternates: list[dict[str, str]] = []
    days_to_next = (next_term.start - reference_date).days
    if timeframe_type in {"current_term", "general"} and 0 <= days_to_next <= 75 and next_term.name != primary.name:
        alternates.append(
            _term_to_dict(
                next_term,
                "medium",
                "Upcoming term begins soon; user phrasing may refer to current or near-upcoming enrollment context.",
            )
        )
    if timeframe_type == "previous_term" and current_term.name != primary.name:
        alternates.append(
            _term_to_dict(
                current_term,
                "medium",
                "Current term included as alternate in case the request is retrospective but needs current status.",
            )
        )

    return {
        "reference_date": reference_date.isoformat(),
        "timezone": timezone or DEFAULT_TIMEZONE,
        "calendar_profile": "byu_semester_with_spring_summer_terms",
        "timeframe_type": timeframe_type,
        "primary_term": _term_to_dict(primary, "high", primary_rationale),
        "alternate_terms": alternates,
        "explicit_time_range": {
            "today": reference_date.isoformat(),
            "next_14_days_end": (reference_date + timedelta(days=14)).isoformat(),
        },
        "guidance": (
            "Interpret ambiguous academic timeframe requests relative to reference_date. "
            "When ambiguity remains, mention the most likely term and one nearby alternate."
        ),
    }


def build_temporal_prompt_note(user_message: str, *, timezone: str = DEFAULT_TIMEZONE) -> str:
    context = infer_timeframe_context(query=user_message, timezone=timezone)
    primary = context.get("primary_term", {})
    alternates = context.get("alternate_terms", [])
    primary_name = str(primary.get("name", "Unknown term"))
    primary_range = f"{primary.get('start_date', '')} to {primary.get('end_date', '')}".strip()
    alternate_names = ", ".join(str(item.get("name", "")) for item in alternates if item.get("name")) or "none"
    return (
        "Temporal grounding: "
        f"today={context['reference_date']} ({context['timezone']}). "
        f"Likely academic term={primary_name} ({primary_range}). "
        f"Near alternates={alternate_names}. "
        "For ambiguous phrases like 'this semester' or 'this term', infer from this grounding and mention uncertainty when needed."
    )
