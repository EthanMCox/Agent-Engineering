from __future__ import annotations

from datetime import datetime, timezone

from backend.canvas_context import build_canvas_prompt_context
from backend.canvas_context import extract_course_ids


class FakeContentItem:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeToolResult:
    def __init__(self, lines: list[str]) -> None:
        self.content = [FakeContentItem("\n".join(lines))]


def test_build_canvas_prompt_context_includes_courses_and_assignments() -> None:
    courses = FakeToolResult(
        [
            "| id | name |",
            "| 1 | CS 301R |",
            "| 2 | Math 110 |",
        ]
    )
    assignments_by_course = {
        "1": FakeToolResult(
            [
                "| id | name | due_at |",
                "| 10 | Project 1 | 2026-03-25T06:00:00Z |",
            ]
        )
    }

    result = build_canvas_prompt_context(
        courses_result=courses,
        assignments_by_course=assignments_by_course,
        now=datetime(2026, 3, 23, tzinfo=timezone.utc),
    )

    assert "Canvas context (grounding data):" in result.prompt_context
    assert "Assignments for course 1:" in result.prompt_context
    assert len(result.sources) == 2
    assert {src.source_id for src in result.sources} == {"list_courses", "list_assignments"}


def test_build_canvas_prompt_context_handles_empty_results() -> None:
    class EmptyToolResult:
        content: list[object] = []

    result = build_canvas_prompt_context(
        courses_result=EmptyToolResult(),
        assignments_by_course={},
        now=datetime(2026, 3, 23, tzinfo=timezone.utc),
    )

    assert "Courses: none returned or unavailable." in result.prompt_context
    assert result.sources == []


def test_extract_course_ids_prefers_structured_then_fallback() -> None:
    class StructuredResult:
        structured_content = {"courses": [{"id": 7}, {"id": "9"}]}
        content: list[object] = []

    ids = extract_course_ids(StructuredResult(), limit=2)
    assert ids == [7, 9]

    markdown_result = FakeToolResult(["| id | name |", "| 11 | Biology |"])
    fallback_ids = extract_course_ids(markdown_result, limit=1)
    assert fallback_ids == [11]
