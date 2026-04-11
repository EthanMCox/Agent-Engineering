from __future__ import annotations

import asyncio

import pytest

from backend.tool_registry import CanvasToolRegistry
from backend.tool_registry import parse_tool_arguments
from backend.settings import build_settings
from backend.context_budget import ContextBudgetPlan


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
        assert tool_name in {"list_courses", "list_assignments", "canvas_list_assignments", "canvas_get_assignment"}
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
    assert "canvas_submit_grade" not in tool_names
    for tool in tools:
        assert tool["type"] == "function"
        assert tool["strict"] is False
        assert tool["parameters"]["additionalProperties"] is False


def test_dispatch_mcp_tool_returns_sources() -> None:
    settings = build_settings({"CANVAS_MCP_ASSIGNMENTS_LIMIT": "8"})
    registry = CanvasToolRegistry(FakeMCPClient(), settings)
    result = asyncio.run(
        registry.dispatch_tool_call(
            "list_assignments",
            {"course_id": 10, "limit": 5},
            session_id="test-session",
            user_question="what is due soon?",
            budget_plan=ContextBudgetPlan(
                max_input_tokens=220000,
                reserved_output_tokens=24000,
                reserved_system_tokens=6000,
                max_tool_tokens_per_append=12000,
            ),
            current_prompt_tokens=1000,
            summarize_func=None,
        )
    )
    assert "items" in result.output_text
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
            budget_plan=ContextBudgetPlan(
                max_input_tokens=220000,
                reserved_output_tokens=24000,
                reserved_system_tokens=6000,
                max_tool_tokens_per_append=12000,
            ),
            current_prompt_tokens=1000,
            summarize_func=None,
        )
    )
    assert "result_id=" in result.output_text
    assert "page=1/" in result.sources[0]["details"]


def test_canvas_query_tool_supports_fields_wrapper_args() -> None:
    settings = build_settings({})
    registry = CanvasToolRegistry(FakeMCPClient(), settings)
    result = asyncio.run(
        registry.dispatch_tool_call(
            "canvas_query_tool",
            {
                "tool_name": "list_assignments",
                "args": {"course_id": 10},
                "fields": ["id", "name", "description"],
                "mediation_mode": "full_if_fits",
            },
            session_id="session-fields",
            user_question="show assignment description",
            budget_plan=ContextBudgetPlan(
                max_input_tokens=220000,
                reserved_output_tokens=24000,
                reserved_system_tokens=6000,
                max_tool_tokens_per_append=12000,
            ),
            current_prompt_tokens=1000,
            summarize_func=None,
        )
    )
    assert "result_id=" in result.output_text
    assert "\"description\"" in result.output_text


def test_full_mode_respects_budget_and_requests_pagination() -> None:
    settings = build_settings({})
    registry = CanvasToolRegistry(FakeMCPClient(), settings)
    result = asyncio.run(
        registry.dispatch_tool_call(
            "canvas_query_tool",
            {
                "tool_name": "list_assignments",
                "args": {"course_id": 10},
                "mediation_mode": "full",
            },
            session_id="session-full-budget",
            user_question="give me full object",
            budget_plan=ContextBudgetPlan(
                max_input_tokens=1200,
                reserved_output_tokens=400,
                reserved_system_tokens=300,
                max_tool_tokens_per_append=100,
            ),
            current_prompt_tokens=700,
            summarize_func=None,
        )
    )
    assert "context budget" in result.output_text.lower()


def test_canvas_query_tool_requires_args_object() -> None:
    settings = build_settings({})
    registry = CanvasToolRegistry(FakeMCPClient(), settings)
    with pytest.raises(ValueError, match="requires 'args'"):
        asyncio.run(
            registry.dispatch_tool_call(
                "canvas_query_tool",
                {
                    "tool_name": "list_assignments",
                    "mediation_mode": "compact",
                },
                session_id="session-missing-args",
                user_question="show assignments",
                budget_plan=ContextBudgetPlan(
                    max_input_tokens=220000,
                    reserved_output_tokens=24000,
                    reserved_system_tokens=6000,
                    max_tool_tokens_per_append=12000,
                ),
                current_prompt_tokens=1000,
                summarize_func=None,
            )
        )


def test_direct_assignment_call_uses_detail_first_defaults_with_provenance() -> None:
    settings = build_settings({})
    registry = CanvasToolRegistry(FakeMCPClient(), settings)
    result = asyncio.run(
        registry.dispatch_tool_call(
            "canvas_get_assignment",
            {"course_id": 10, "assignment_id": 22},
            session_id="session-assignment-detail",
            user_question="show full assignment details",
            budget_plan=ContextBudgetPlan(
                max_input_tokens=220000,
                reserved_output_tokens=24000,
                reserved_system_tokens=6000,
                max_tool_tokens_per_append=12000,
            ),
            current_prompt_tokens=1000,
            summarize_func=None,
        )
    )
    assert "\"description\"" in result.output_text
    assert "\"rubric\"" in result.output_text
    assert "fields_present" in result.output_text


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
                budget_plan=ContextBudgetPlan(
                    max_input_tokens=220000,
                    reserved_output_tokens=24000,
                    reserved_system_tokens=6000,
                    max_tool_tokens_per_append=12000,
                ),
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
