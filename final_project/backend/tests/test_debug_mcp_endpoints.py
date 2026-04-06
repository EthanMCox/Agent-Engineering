from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app import app
from backend.app import canvas_mcp_client
from backend.app import canvas_tool_registry


def test_debug_list_mcp_tools(monkeypatch) -> None:
    async def fake_list_tool_definitions():
        return [
            {"name": "canvas_list_courses", "description": "List courses", "input_schema": {}},
            {"name": "canvas_get_course_grades", "description": "Get grades", "input_schema": {}},
        ]

    monkeypatch.setattr(canvas_mcp_client, "list_tool_definitions", fake_list_tool_definitions)

    with TestClient(app) as client:
        response = client.get("/api/debug/mcp/tools")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["count"] == 2
    assert "canvas_list_courses" in payload["tools"]


def test_debug_call_mcp_tool(monkeypatch) -> None:
    async def fake_dispatch(tool_name: str, arguments: dict):
        assert tool_name == "canvas_list_courses"
        assert arguments == {"include_ended": False}
        return type(
            "DispatchResult",
            (),
            {
                "output_text": "Canvas MCP tool result (canvas_list_courses): []",
                "sources": [{"source_id": "canvas_list_courses"}],
            },
        )()

    monkeypatch.setattr(canvas_tool_registry, "dispatch_tool_call", fake_dispatch)

    with TestClient(app) as client:
        response = client.post(
            "/api/debug/mcp/call",
            json={
                "tool_name": "canvas_list_courses",
                "arguments": {"include_ended": False},
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["tool_name"] == "canvas_list_courses"
    assert payload["output_chars"] is not None
    assert payload["sources"][0]["source_id"] == "canvas_list_courses"
