from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from backend.context_budget import ContextBudgetPlan
from backend.settings import build_settings
from backend.tool_registry import CanvasToolRegistry, parse_tool_arguments


class FakeMCPClient:
    def __init__(self, enabled: bool = True, status: str = "ready", last_error: str | None = None) -> None:
        self._enabled = enabled
        self._status = status
        self._last_error = last_error

    async def health(self):
        return type(
            "Health",
            (),
            {
                "enabled": self._enabled,
                "connected": self._status == "ready",
                "status": self._status,
                "last_error": self._last_error,
            },
        )()

    async def list_tool_definitions(self):
        return [
            {
                "name": "list_courses",
                "description": "List Canvas courses",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
            {
                "name": "list_assignments",
                "description": "List assignments for a course",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "course_id": {"type": "integer"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["course_id"],
                },
            },
            {
                "name": "canvas_submit_grade",
                "description": "Submit grades for an assignment",
                "input_schema": {
                    "type": "object",
                    "properties": {"assignment_id": {"type": "integer"}},
                    "required": ["assignment_id"],
                },
            },
            {
                "name": "canvas_get_assignment",
                "description": "Get assignment details",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "course_id": {"type": "integer"},
                        "assignment_id": {"type": "integer"},
                    },
                    "required": ["course_id", "assignment_id"],
                },
            },
        ]

    async def call_tool(self, tool_name: str, arguments: dict):
        assert isinstance(arguments, dict)
        if tool_name == "canvas_get_assignment":
            return type(
                "Result",
                (),
                {
                    "structured_content": {
                        "id": 22,
                        "name": "Project 1",
                        "description": "Build budget spreadsheet and reflection.",
                        "due_at": "2026-04-01T06:00:00Z",
                        "points_possible": 100,
                        "rubric": [{"id": "r1", "description": "Accuracy"}],
                    }
                },
            )()
        return type(
            "Result",
            (),
            {
                "structured_content": {
                    "assignments": [
                        {
                            "id": 22,
                            "name": "Project 1",
                            "description": "Build budget spreadsheet and reflection.",
                            "due_at": "2026-04-01T06:00:00Z",
                            "points_possible": 100,
                            "rubric": [{"id": "r1", "description": "Accuracy"}],
                        }
                    ]
                }
            },
        )()


def _budget(max_tool_tokens: int = 12000) -> ContextBudgetPlan:
    return ContextBudgetPlan(
        max_input_tokens=220000,
        reserved_output_tokens=24000,
        reserved_system_tokens=6000,
        max_tool_tokens_per_append=max_tool_tokens,
    )


def _parse_envelope(output_text: str) -> dict[str, Any]:
    return json.loads(output_text)


def _large_assignments_payload(count: int = 90, description_chars: int = 480) -> dict[str, Any]:
    assignments: list[dict[str, Any]] = []
    for idx in range(count):
        assignments.append(
            {
                "id": idx + 1,
                "name": f"Assignment {idx + 1}",
                "description": "x" * description_chars,
                "due_at": "2026-04-01T06:00:00Z",
                "points_possible": 100 + idx,
                "html_url": f"https://example.edu/assignments/{idx + 1}",
                "workflow_state": "published",
                "rubric": [{"id": f"r{idx}", "description": "Accuracy"}],
            }
        )
    return {"assignments": assignments}


def test_registry_returns_no_tools_when_mcp_disabled() -> None:
    settings = build_settings({})
    registry = CanvasToolRegistry(FakeMCPClient(enabled=False, status="disabled"), settings)
    tools, reason = asyncio.run(registry.get_openai_tools())
    assert tools == []
    assert reason is not None
    assert "disabled" in reason


def test_registry_tools_have_compatible_schema() -> None:
    settings = build_settings({})
    registry = CanvasToolRegistry(FakeMCPClient(), settings)
    tools, reason = asyncio.run(registry.get_openai_tools())
    assert reason is None
    assert tools
    tool_names = {tool["name"] for tool in tools}
    assert "canvas_query_tool" in tool_names
    assert "canvas_get_result_page" in tool_names
    assert "canvas_resolve_timeframe" in tool_names
    assert "canvas_submit_grade" not in tool_names
    for tool in tools:
        assert tool["type"] == "function"
        assert tool["strict"] is False
        assert tool["parameters"]["additionalProperties"] is False


def test_dispatch_mcp_tool_returns_envelope_pass_through() -> None:
    settings = build_settings({})
    registry = CanvasToolRegistry(FakeMCPClient(), settings)
    result = asyncio.run(
        registry.dispatch_tool_call(
            "list_assignments",
            {"course_id": 10, "limit": 5},
            session_id="test-session",
            user_question="what is due soon?",
            budget_plan=_budget(),
            current_prompt_tokens=1000,
            summarize_func=None,
        )
    )
    envelope = _parse_envelope(result.output_text)
    assert envelope["version"] == "mcp_response_envelope.v1"
    assert envelope["policy_path"] == "pass_through"
    assert envelope["payload"] is not None
    assert "assignments" in envelope["payload"]
    assert len(result.sources) == 1
    assert result.sources[0]["source_id"] == "list_assignments"


def test_dispatch_high_volume_auto_routes_to_paginated_result() -> None:
    settings = build_settings({})
    registry = CanvasToolRegistry(FakeMCPClient(), settings)
    result = asyncio.run(
        registry.dispatch_tool_call(
            "canvas_list_assignments",
            {"course_id": 10, "include_submissions": True},
            session_id="session-paginate",
            user_question="show me all assignments",
            budget_plan=_budget(),
            current_prompt_tokens=1000,
            summarize_func=None,
        )
    )
    envelope = _parse_envelope(result.output_text)
    assert envelope["pagination"]["result_id"]
    assert envelope["pagination"]["page"] == 1
    assert "page=1/" in result.sources[0]["details"]


def test_canvas_query_tool_accepts_legacy_wrapper_args() -> None:
    settings = build_settings({})
    registry = CanvasToolRegistry(FakeMCPClient(), settings)
    result = asyncio.run(
        registry.dispatch_tool_call(
            "canvas_query_tool",
            {
                "tool_name": "list_assignments",
                "args": {"course_id": 10},
                "fields": ["id", "name", "description"],
                "mediation_mode": "full",
                "include_description": True,
                "include_rubric": True,
            },
            session_id="session-fields",
            user_question="show assignment description",
            budget_plan=_budget(),
            current_prompt_tokens=1000,
            summarize_func=None,
        )
    )
    envelope = _parse_envelope(result.output_text)
    assert envelope["tool"] == "list_assignments"
    assert envelope["version"] == "mcp_response_envelope.v1"


def test_large_payload_triggers_projection_with_field_selector() -> None:
    settings = build_settings({})
    client = FakeMCPClient()

    async def fake_call_tool(tool_name: str, arguments: dict):
        return type("Result", (), {"structured_content": _large_assignments_payload()})()

    async def fake_summarizer(instruction: str, content: str, max_output_tokens: int) -> str:
        if "retain_fields" in instruction:
            return json.dumps({"retain_fields": ["id", "name", "due_at", "points_possible"]})
        return json.dumps(
            {
                "key_facts": ["Projected fields selected."],
                "ids": ["1"],
                "dates": ["2026-04-01T06:00:00Z"],
                "numeric_values": ["100"],
                "constraints": [],
                "missing_data": [],
            }
        )

    client.call_tool = fake_call_tool  # type: ignore[method-assign]
    registry = CanvasToolRegistry(client, settings)
    result = asyncio.run(
        registry.dispatch_tool_call(
            "list_assignments",
            {"course_id": 10},
            session_id="session-projected",
            user_question="give me ids and due dates",
            budget_plan=_budget(max_tool_tokens=8000),
            current_prompt_tokens=0,
            summarize_func=fake_summarizer,
        )
    )
    envelope = _parse_envelope(result.output_text)
    assert envelope["policy_path"] == "projected"
    assert envelope["fields_dropped"]
    first_item = envelope["payload"]["assignments"][0]
    assert "description" not in first_item
    assert "id" in first_item


def test_large_payload_triggers_chunk_summarization_and_hierarchical_merge() -> None:
    settings = build_settings({})
    client = FakeMCPClient()
    merge_calls = {"count": 0}
    chunk_calls = {"count": 0}

    async def fake_call_tool(tool_name: str, arguments: dict):
        return type("Result", (), {"structured_content": _large_assignments_payload(count=140, description_chars=520)})()

    async def fake_summarizer(instruction: str, content: str, max_output_tokens: int) -> str:
        if "retain_fields" in instruction:
            return json.dumps({"retain_fields": ["id", "name", "due_at", "points_possible"]})
        if "Merge child summaries" in instruction:
            merge_calls["count"] += 1
            return json.dumps(
                {
                    "key_facts": ["Merged summary"],
                    "ids": ["1", "2"],
                    "dates": ["2026-04-01T06:00:00Z"],
                    "numeric_values": ["100", "120"],
                    "constraints": ["Deadlines matter"],
                    "missing_data": [],
                }
            )
        chunk_calls["count"] += 1
        return json.dumps(
            {
                "key_facts": ["Chunk summary"],
                "ids": ["1"],
                "dates": ["2026-04-01T06:00:00Z"],
                "numeric_values": ["100"],
                "constraints": [],
                "missing_data": [],
            }
        )

    client.call_tool = fake_call_tool  # type: ignore[method-assign]
    registry = CanvasToolRegistry(client, settings)
    result = asyncio.run(
        registry.dispatch_tool_call(
            "list_assignments",
            {"course_id": 10},
            session_id="session-summary",
            user_question="summarize all key facts",
            budget_plan=_budget(max_tool_tokens=400),
            current_prompt_tokens=0,
            summarize_func=fake_summarizer,
        )
    )
    envelope = _parse_envelope(result.output_text)
    assert envelope["policy_path"] == "chunk_summarized"
    assert envelope["summary"] is not None
    assert envelope["payload"] is None
    assert chunk_calls["count"] >= 1
    assert merge_calls["count"] >= 1


def test_large_payload_summarizer_failure_uses_deterministic_fallback() -> None:
    settings = build_settings({})
    client = FakeMCPClient()

    async def fake_call_tool(tool_name: str, arguments: dict):
        return type("Result", (), {"structured_content": _large_assignments_payload(count=120, description_chars=520)})()

    async def failing_summarizer(instruction: str, content: str, max_output_tokens: int) -> str:
        raise RuntimeError("summarizer unavailable")

    client.call_tool = fake_call_tool  # type: ignore[method-assign]
    registry = CanvasToolRegistry(client, settings)
    result = asyncio.run(
        registry.dispatch_tool_call(
            "list_assignments",
            {"course_id": 10},
            session_id="session-fallback",
            user_question="what should I focus on",
            budget_plan=_budget(max_tool_tokens=300),
            current_prompt_tokens=0,
            summarize_func=failing_summarizer,
        )
    )
    envelope = _parse_envelope(result.output_text)
    assert envelope["policy_path"] == "deterministic_fallback"
    assert envelope["status"] == "degraded"
    assert envelope["warnings"]


def test_budget_pressure_returns_safe_json_envelope() -> None:
    settings = build_settings({})
    registry = CanvasToolRegistry(FakeMCPClient(), settings)
    result = asyncio.run(
        registry.dispatch_tool_call(
            "list_assignments",
            {"course_id": 10},
            session_id="session-budget",
            user_question="show all details",
            budget_plan=ContextBudgetPlan(
                max_input_tokens=1200,
                reserved_output_tokens=400,
                reserved_system_tokens=300,
                max_tool_tokens_per_append=100,
            ),
            current_prompt_tokens=900,
            summarize_func=None,
        )
    )
    envelope = _parse_envelope(result.output_text)
    assert envelope["available_tool_tokens"] == 0
    assert envelope["policy_path"] == "deterministic_fallback"
    assert envelope["payload"] is not None


def test_direct_assignment_call_uses_structured_envelope() -> None:
    settings = build_settings({})
    registry = CanvasToolRegistry(FakeMCPClient(), settings)
    result = asyncio.run(
        registry.dispatch_tool_call(
            "canvas_get_assignment",
            {"course_id": 10, "assignment_id": 22},
            session_id="session-assignment-detail",
            user_question="show assignment details",
            budget_plan=_budget(),
            current_prompt_tokens=1000,
            summarize_func=None,
        )
    )
    envelope = _parse_envelope(result.output_text)
    assert envelope["tool"] == "canvas_get_assignment"
    assert envelope["version"] == "mcp_response_envelope.v1"
    assert envelope["payload"] is not None


def test_canvas_resolve_timeframe_handles_this_semester_in_march() -> None:
    settings = build_settings({})
    registry = CanvasToolRegistry(FakeMCPClient(), settings)
    result = asyncio.run(
        registry.dispatch_tool_call(
            "canvas_resolve_timeframe",
            {
                "query": "what classes am i taking this semester?",
                "reference_date": "2026-03-15",
                "timezone": "America/Denver",
            },
            session_id="session-timeframe",
            user_question="what classes am i taking this semester?",
            budget_plan=_budget(),
            current_prompt_tokens=100,
            summarize_func=None,
        )
    )
    envelope = _parse_envelope(result.output_text)
    payload = envelope["payload"]
    assert payload["primary_term"]["name"] == "Winter Semester"
    alternate_names = {item["name"] for item in payload["alternate_terms"]}
    assert "Spring Term" in alternate_names


def test_dispatch_blocks_denied_tool_even_if_called_directly() -> None:
    settings = build_settings({})
    registry = CanvasToolRegistry(FakeMCPClient(), settings)
    with pytest.raises(ValueError, match="disabled by MCP tool governance policy"):
        asyncio.run(
            registry.dispatch_tool_call(
                "canvas_submit_grade",
                {"assignment_id": 22},
                session_id="session-denied-call",
                user_question="submit grade",
                budget_plan=_budget(),
                current_prompt_tokens=1000,
                summarize_func=None,
            )
        )


def test_parse_tool_arguments_requires_object_json() -> None:
    assert parse_tool_arguments("{}") == {}
    with pytest.raises(ValueError):
        parse_tool_arguments("[]")
    with pytest.raises(ValueError):
        parse_tool_arguments("{invalid")
