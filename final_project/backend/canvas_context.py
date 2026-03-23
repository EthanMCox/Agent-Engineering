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
            if "|" in line:
                rows.append({"raw": line.strip()})
            else:
                rows.append({"raw": line.strip()})
    return rows


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
