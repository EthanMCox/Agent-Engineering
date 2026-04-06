from __future__ import annotations

import asyncio

import pytest

from backend.tool_registry import CanvasToolRegistry
from backend.tool_registry import parse_tool_arguments
from backend.settings import build_settings


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
        ]

    async def call_tool(self, tool_name: str, arguments: dict):
        assert tool_name in {"list_courses", "list_assignments"}
        assert isinstance(arguments, dict)
        return type(
            "Result",
            (),
            {
                "structured_content": {
                    "assignments": [
                        {
                            "id": 22,
                            "name": "Project 1",
                            "due_at": "2026-04-01T06:00:00Z",
                            "points_possible": 100,
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
    for tool in tools:
        assert tool["type"] == "function"
        assert tool["strict"] is False
        assert tool["parameters"]["additionalProperties"] is False


def test_dispatch_mcp_tool_returns_sources() -> None:
    settings = build_settings({"CANVAS_MCP_ASSIGNMENTS_LIMIT": "8"})
    registry = CanvasToolRegistry(FakeMCPClient(), settings)
    result = asyncio.run(registry.dispatch_tool_call("list_assignments", {"course_id": 10, "limit": 5}))
    assert "Canvas MCP tool result (list_assignments)" in result.output_text
    assert len(result.sources) == 1
    assert result.sources[0]["source_id"] == "list_assignments"


def test_parse_tool_arguments_requires_object_json() -> None:
    assert parse_tool_arguments("{}") == {}
    with pytest.raises(ValueError):
        parse_tool_arguments("[]")
    with pytest.raises(ValueError):
        parse_tool_arguments("{invalid")
