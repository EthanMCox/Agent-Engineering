from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app import app
from backend.app import canvas_tool_registry
from backend.app import client
from backend.app import settings


class FakeUsage:
    def __init__(self, input_tokens: int, output_tokens: int, total_tokens: int) -> None:
        self._payload = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
        }

    def model_dump(self):
        return dict(self._payload)


class FakeFunctionCall:
    type = "function_call"

    def __init__(self, name: str, arguments: str, call_id: str) -> None:
        self.name = name
        self.arguments = arguments
        self.call_id = call_id


class FakeMessageChunk:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeMessage:
    type = "message"

    def __init__(self, text: str) -> None:
        self.content = [FakeMessageChunk(text)]


class FakeResponse:
    def __init__(self, output: list[object], usage: FakeUsage) -> None:
        self.output = output
        self.usage = usage


def test_chat_performs_tool_call_and_returns_sources(monkeypatch) -> None:
    settings.openai_api_key = "test-key"

    async def fake_get_tools():
        return (
            [
                {
                    "type": "function",
                    "name": "list_courses",
                    "description": "List courses",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                        "additionalProperties": False,
                    },
                    "strict": True,
                }
            ],
            None,
        )

    async def fake_dispatch(
        tool_name: str,
        arguments: dict,
        *,
        session_id: str,
        user_question: str,
        budget_plan,
        current_prompt_tokens: int,
        summarize_func,
    ):
        assert tool_name == "list_courses"
        assert arguments == {}
        assert session_id == "tool-seq"
        assert user_question
        assert current_prompt_tokens >= 0
        return type(
            "DispatchResult",
            (),
            {
                "output_text": "Canvas courses:\n- CS 301R (course_id: 10)",
                "sources": [
                    {
                        "source_type": "canvas_tool",
                        "source_id": "list_courses",
                        "label": "Canvas courses",
                    "details": "Data fetched from Canvas MCP list_courses.",
                    }
                ],
            },
        )()

    responses = [
        FakeResponse(
            output=[FakeFunctionCall("list_courses", "{}", "call_1")],
            usage=FakeUsage(10, 1, 11),
        ),
        FakeResponse(
            output=[FakeMessage("You have one active course in Canvas.")],
            usage=FakeUsage(8, 12, 20),
        ),
    ]

    class FakeResponsesAPI:
        async def create(self, **kwargs):
            return responses.pop(0)

    monkeypatch.setattr(canvas_tool_registry, "get_openai_tools", fake_get_tools)
    monkeypatch.setattr(canvas_tool_registry, "dispatch_tool_call", fake_dispatch)
    monkeypatch.setattr(client, "responses", FakeResponsesAPI())

    with TestClient(app) as test_client:
        response = test_client.post(
            "/api/chat",
            json={"session_id": "tool-seq", "message": "what classes am i in"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert "one active course" in payload["markdown"].lower()
    assert payload["sources"] is not None
    assert payload["sources"][0]["source_id"] == "list_courses"
    assert payload["usage"]["total_tokens"] == 31
