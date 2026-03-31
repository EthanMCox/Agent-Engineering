from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class CanvasSource:
    source_type: str
    source_id: str
    label: str
    details: str


@dataclass(slots=True)
class CanvasContextResult:
    prompt_context: str
    sources: list[CanvasSource]


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _extract_rows(tool_result: Any) -> list[dict[str, Any]]:
    structured = getattr(tool_result, "structured_content", None)
    if isinstance(structured, dict):
        for key in ("courses", "items", "assignments", "data"):
            value = structured.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    if isinstance(structured, list):
        return [item for item in structured if isinstance(item, dict)]

    content = getattr(tool_result, "content", None)
    if not content or not isinstance(content, list):
        return []

    rows: list[dict[str, Any]] = []
    for item in content:
        text = _to_text(getattr(item, "text", ""))
        if not text:
            continue
        for line in text.splitlines():
            # The canvas-mcp-server tools often return markdown tables.
            # Keep this parser forgiving so we still extract context from plain text responses.
            rows.append({"raw": line.strip()})
    return rows


def extract_course_ids(tool_result: Any, limit: int) -> list[int]:
    ids: list[int] = []
    seen: set[int] = set()

    for row in _extract_rows(tool_result):
        value = row.get("id")
        try:
            if value is None:
                continue
            course_id = int(value)
        except (TypeError, ValueError):
            continue
        if course_id in seen:
            continue
        seen.add(course_id)
        ids.append(course_id)
        if len(ids) >= limit:
            return ids

    # Fallback: parse markdown/plain-text rows.
    for row in _extract_rows(tool_result):
        raw = _to_text(row.get("raw"))
        for part in raw.split("|"):
            piece = part.strip()
            if piece.isdigit():
                course_id = int(piece)
                if course_id in seen:
                    continue
                seen.add(course_id)
                ids.append(course_id)
                if len(ids) >= limit:
                    return ids
    return ids


def build_canvas_prompt_context(
    *,
    courses_result: Any,
    assignments_by_course: dict[str, Any],
    now: datetime | None = None,
) -> CanvasContextResult:
    ts = now or datetime.now(timezone.utc)
    course_rows = _extract_rows(courses_result)

    sources: list[CanvasSource] = []
    lines: list[str] = [
        "Canvas context (grounding data):",
        f"- Retrieved at UTC: {ts.isoformat()}",
    ]

    if course_rows:
        lines.append("- Courses: available (raw summary captured).")
        preview = "\n".join(f"  - {row['raw']}" for row in course_rows[:8])
        lines.append(preview)
        sources.append(
            CanvasSource(
                source_type="tool",
                source_id="list_courses",
                label="Canvas courses",
                details="Data fetched from Canvas MCP tool list_courses.",
            )
        )
    else:
        lines.append("- Courses: none returned or unavailable.")

    for course_id, assignments_result in assignments_by_course.items():
        assignment_rows = _extract_rows(assignments_result)
        if assignment_rows:
            lines.append(f"- Assignments for course {course_id}:")
            lines.extend(f"  - {row['raw']}" for row in assignment_rows[:10])
            sources.append(
                CanvasSource(
                    source_type="tool",
                    source_id="list_assignments",
                    label=f"Assignments for course {course_id}",
                    details=f"Data fetched from Canvas MCP tool list_assignments for course {course_id}.",
                )
            )
        else:
            lines.append(f"- Assignments for course {course_id}: none returned or unavailable.")

    return CanvasContextResult(prompt_context="\n".join(lines), sources=sources)
