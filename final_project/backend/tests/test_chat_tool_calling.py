from __future__ import annotations

import asyncio
import json

from fastapi.testclient import TestClient

import backend.app as app_module
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


def _fake_message_response(text: str) -> FakeResponse:
    return FakeResponse(output=[FakeMessage(text)], usage=FakeUsage(0, 0, 0))


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
                "output_text": json.dumps(
                    {
                        "version": "mcp_response_envelope.v1",
                        "tool": "list_courses",
                        "status": "ok",
                        "policy_path": "pass_through",
                        "payload": {"courses": [{"id": 10, "name": "CS 301R"}]},
                    }
                ),
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

    model_responses = [
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
        def __init__(self) -> None:
            self._idx = 0

        async def create(self, **kwargs):
            input_items = kwargs.get("input", [])
            user_content = ""
            if isinstance(input_items, list):
                for item in input_items:
                    if isinstance(item, dict) and item.get("role") == "user":
                        user_content = str(item.get("content", ""))
                        break
            if "final response quality guard" in user_content.lower():
                return _fake_message_response(
                    json.dumps(
                        {
                            "action": "ok",
                            "rewritten_response": "",
                            "reason": "Clear user-facing response.",
                        }
                    )
                )
            if "update the session memory json" in user_content.lower():
                return _fake_message_response(
                    json.dumps(
                        {
                            "conversation_summary": "User asked about classes.",
                            "active_goals": ["See active courses"],
                            "confirmed_facts": ["One active course found"],
                            "open_questions": [],
                            "recent_tool_findings": ["list_courses returned CS 301R"],
                        }
                    )
                )
            response = model_responses[self._idx]
            self._idx += 1
            return response

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


def test_final_response_guard_rewrites_internal_jargon(monkeypatch) -> None:
    async def fake_small_model(instruction: str, content: str, max_output_tokens: int = 700) -> str:
        return json.dumps(
            {
                "action": "rewrite",
                "rewritten_response": "You have one active course this semester: CS 301R.",
                "reason": "Removed internal language.",
            }
        )

    monkeypatch.setattr(app_module, "_summarize_text_with_small_model", fake_small_model)
    decision = asyncio.run(
        app_module._evaluate_final_response_guard(
            user_message="What classes am I taking?",
            assistant_text="I used tool calls and a JSON envelope to confirm your courses.",
        )
    )
    assert decision.action == "rewrite"
    assert "tool calls" not in decision.rewritten_response.lower()
    assert "json envelope" not in decision.rewritten_response.lower()
    assert "cs 301r" in decision.rewritten_response.lower()


def test_final_response_guard_returns_structured_rewrite_decision(monkeypatch) -> None:
    async def fake_small_model(instruction: str, content: str, max_output_tokens: int = 700) -> str:
        return json.dumps(
            {
                "action": "rewrite",
                "rewritten_response": "You have one active course this semester: CS 301R.",
                "reason": "Removed internal language.",
            }
        )

    monkeypatch.setattr(app_module, "_summarize_text_with_small_model", fake_small_model)
    decision = asyncio.run(
        app_module._evaluate_final_response_guard(
            user_message="What classes am I taking?",
            assistant_text="I used tool calls and a JSON envelope to confirm your courses.",
        )
    )
    assert decision.action == "rewrite"
    assert decision.rewritten_response == "You have one active course this semester: CS 301R."
    assert "internal language" in decision.reason.lower()


def test_final_response_guard_handles_jumbled_output(monkeypatch) -> None:
    async def fake_small_model(instruction: str, content: str, max_output_tokens: int = 700) -> str:
        return json.dumps(
            {
                "action": "error",
                "rewritten_response": app_module.FINAL_RESPONSE_RETRY_MESSAGE,
                "reason": "Jumbled output.",
            }
        )

    monkeypatch.setattr(app_module, "_summarize_text_with_small_model", fake_small_model)
    decision = asyncio.run(
        app_module._evaluate_final_response_guard(
            user_message="What should I study today?",
            assistant_text="qzxv!! ## @@ blrptn mmnnk %%&&",
        )
    )
    assert decision.action == "error"
    assert decision.rewritten_response == app_module.FINAL_RESPONSE_RETRY_MESSAGE
