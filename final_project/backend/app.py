from __future__ import annotations

import logging
import re
import time
from contextlib import asynccontextmanager
from typing import Any
from typing import Literal as TypingLiteral
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from .mcp_client import CanvasMCPClient
from .settings import AppSettings
from .settings import load_settings
from .tool_registry import CanvasToolRegistry
from .tool_registry import parse_tool_arguments

SYSTEM_PROMPT = (
    "You are a helpful study assistant."
    "Be concise, honest, and practical. "
    "If you are unsure, clearly say so instead of making up facts. "
    "For Canvas-related questions (courses, assignments, deadlines, grades, study priorities), call Canvas tools first before answering. "
    "Prefer Canvas tool-grounded facts over assumptions. "
    "If Canvas tools are unavailable or incomplete, explicitly say what is uncertain and what data is missing. "
    "When you use Canvas tool data, cite it briefly in bullet form. "
    "Format answers cleanly: use short paragraphs, bullet lists when helpful, and fenced code blocks only when needed. "
    "Output markdown only. Do not output raw renderable HTML, CSS, JavaScript, or inline style attributes. "
    "If a user asks for HTML/CSS/JS examples, provide them inside fenced code blocks (for example, ```html ... ```), not as renderable markup. "
    "If a user asks for color/styling that requires CSS, provide CSS as a fenced code block and explain briefly. "
    "You may use markdown formatting such as headings, bold, italics, lists, blockquotes, and inline code."
)
DEFAULT_MODEL = "gpt-5-nano"
MAX_TURNS = 12
MAX_TOOL_ROUNDS = 4
settings: AppSettings = load_settings()


def configure_logging() -> logging.Logger:
    level_name = settings.log_level.upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    return logging.getLogger("canvas_study_coach.backend")


logger = configure_logging()


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    markdown: str
    content_type: Literal["text/markdown"] = "text/markdown"
    format: Literal["markdown"] = "markdown"
    model: str
    usage: dict[str, Any] | None = None
    sources: list[dict[str, str]] | None = None


class ResetRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=200)


class ResetResponse(BaseModel):
    ok: bool


class HealthResponse(BaseModel):
    ok: bool
    model: str
    mcp_canvas_ok: bool
    mcp_canvas_enabled: bool
    mcp_canvas_status: TypingLiteral["disabled", "starting", "ready", "degraded", "error"]
    mcp_canvas_error: str | None = None


canvas_mcp_client = CanvasMCPClient(settings=settings)
canvas_tool_registry = CanvasToolRegistry(canvas_mcp_client, settings=settings)


@asynccontextmanager
async def app_lifespan(_: FastAPI):
    logger.info("Canvas MCP startup config: %s", canvas_mcp_client.startup_summary())
    if canvas_mcp_client.enabled:
        try:
            await canvas_mcp_client.start()
        except Exception as exc:
            logger.exception("Canvas MCP failed to start during app startup: %s", exc)
    yield
    await canvas_mcp_client.stop()


app = FastAPI(title="Canvas Study Coach Chat API", version="0.1.0", lifespan=app_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

client = AsyncOpenAI(api_key=settings.openai_api_key)
conversation_store: dict[str, list[dict[str, str]]] = {}


def active_model() -> str:
    return settings.openai_model or DEFAULT_MODEL


def mask_session_id(session_id: str) -> str:
    if len(session_id) <= 8:
        return session_id
    return f"{session_id[:4]}...{session_id[-4:]}"


def preview_text(text: str, limit: int = 120) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}..."


def ensure_session(session_id: str) -> list[dict[str, str]]:
    if session_id not in conversation_store:
        conversation_store[session_id] = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Keep existing sessions aligned with current prompt updates.
    history = conversation_store[session_id]
    if not history or history[0].get("role") != "system":
        history.insert(0, {"role": "system", "content": SYSTEM_PROMPT})
    else:
        history[0]["content"] = SYSTEM_PROMPT
    return history


def normalize_output_format(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return stripped

    # Convert HTML-like output to fenced code so examples display safely without rendering.
    contains_html_like = re.search(
        r"<\s*(?:div|span|p|h[1-6]|ul|ol|li|strong|em|style|script|table|section|article|header|footer|main|aside|a|img|button|input|form)\b",
        stripped,
        re.IGNORECASE,
    )
    has_code_fence = re.search(r"```[a-zA-Z0-9_-]*\n", stripped) is not None
    if contains_html_like and not has_code_fence:
        logger.warning("Model returned HTML-like content without code fences; wrapping as fenced html block")
        return (
            "Here is the HTML example as code (displayed safely, not rendered):\n\n"
            f"```html\n{stripped}\n```"
        )

    return stripped


def trim_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
    if not history:
        return [{"role": "system", "content": SYSTEM_PROMPT}]

    system_message = history[0]
    turns = history[1:]
    max_messages = MAX_TURNS * 2
    if len(turns) > max_messages:
        turns = turns[-max_messages:]
    return [system_message, *turns]


def merge_usage(totals: dict[str, int], usage_obj: Any | None) -> dict[str, int]:
    if usage_obj is None:
        return totals
    dump = usage_obj.model_dump() if hasattr(usage_obj, "model_dump") else usage_obj
    if not isinstance(dump, dict):
        return totals
    for key, value in dump.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            totals[key] = totals.get(key, 0) + value
    return totals


def extract_assistant_text(response: Any) -> str:
    text_chunks: list[str] = []
    output = getattr(response, "output", None)
    if not isinstance(output, list):
        return ""

    for item in output:
        if getattr(item, "type", None) != "message":
            continue
        for chunk in getattr(item, "content", []):
            chunk_text = getattr(chunk, "text", "")
            if chunk_text:
                text_chunks.append(chunk_text)
    return "".join(text_chunks).strip()


def format_exception(exc: Exception) -> str:
    detail = str(exc).strip()
    if detail:
        return f"{type(exc).__name__}: {detail}"
    return type(exc).__name__


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    logger.debug("Health check requested")
    mcp_health = await canvas_mcp_client.health()
    return HealthResponse(
        ok=True,
        model=active_model(),
        mcp_canvas_ok=mcp_health.connected,
        mcp_canvas_enabled=mcp_health.enabled,
        mcp_canvas_status=mcp_health.status,
        mcp_canvas_error=mcp_health.last_error,
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest) -> ChatResponse:
    masked_session_id = mask_session_id(payload.session_id)
    logger.info("Chat request received session=%s message_chars=%d", masked_session_id, len(payload.message))

    if not settings.openai_api_key:
        logger.error("OPENAI_API_KEY is not configured")
        raise HTTPException(
            status_code=500,
            detail="OPENAI_API_KEY is not configured for the backend service.",
        )

    user_message = payload.message.strip()
    if not user_message:
        logger.warning("Rejected empty message session=%s", masked_session_id)
        raise HTTPException(status_code=400, detail="Message must not be empty.")

    history = ensure_session(payload.session_id)
    logger.debug(
        "Session prepared session=%s history_messages_before_append=%d user_preview=%r",
        masked_session_id,
        len(history),
        preview_text(user_message),
    )
    history.append({"role": "user", "content": user_message})

    try:
        start_time = time.perf_counter()
        selected_model = active_model()
        logger.info(
            "Calling model session=%s model=%s input_messages=%d",
            masked_session_id,
            selected_model,
            len(history),
        )

        tools, unavailable_reason = await canvas_tool_registry.get_openai_tools()
        if tools:
            tool_names = ", ".join(tool["name"] for tool in tools[:30])
            runtime_note = (
                "Canvas tools are available from the mcp-canvas sidecar. "
                f"Available tools: {tool_names}. "
                "For Canvas-related user requests, call the relevant Canvas tools first and ground your answer in tool output."
            )
        else:
            runtime_note = (
                "Canvas tools are unavailable for this request "
                f"({unavailable_reason}). Do not fabricate Canvas facts; state uncertainty and continue with general guidance."
            )
        working_history: list[Any] = [
            history[0],
            {"role": "system", "content": runtime_note},
            *history[1:],
        ]

        sources: list[dict[str, str]] = []
        usage_totals: dict[str, int] = {}
        assistant_text = ""
        tools_enabled_for_turn = bool(tools)

        for round_index in range(1, MAX_TOOL_ROUNDS + 2):
            response = await client.responses.create(
                model=selected_model,
                input=working_history,
                tools=tools if tools_enabled_for_turn else None,
            )
            usage_totals = merge_usage(usage_totals, response.usage)
            working_history.extend(getattr(response, "output", []))

            tool_calls = [
                item for item in getattr(response, "output", []) if getattr(item, "type", None) == "function_call"
            ]
            if tool_calls:
                logger.info(
                    "Tool round session=%s round=%d tool_calls=%d",
                    masked_session_id,
                    round_index,
                    len(tool_calls),
                )

            assistant_text = extract_assistant_text(response)
            if assistant_text:
                break

            if not tool_calls:
                break

            if round_index > MAX_TOOL_ROUNDS:
                assistant_text = (
                    "I reached the Canvas tool-call limit for this turn. "
                    "Please narrow your request or ask for one course at a time."
                )
                logger.warning("Tool loop limit reached session=%s", masked_session_id)
                break

            for tool_call in tool_calls:
                tool_name = getattr(tool_call, "name", "")
                call_id = getattr(tool_call, "call_id", "")
                raw_arguments = getattr(tool_call, "arguments", "") or "{}"
                try:
                    arguments = parse_tool_arguments(raw_arguments)
                    logger.info(
                        "Dispatching tool session=%s tool=%s call_id=%s argument_keys=%s",
                        masked_session_id,
                        tool_name,
                        call_id,
                        sorted(arguments.keys()),
                    )
                    dispatch_result = await canvas_tool_registry.dispatch_tool_call(tool_name, arguments)
                    output_text = dispatch_result.output_text
                    logger.info(
                        "Tool execution succeeded session=%s tool=%s output_chars=%d",
                        masked_session_id,
                        tool_name,
                        len(output_text),
                    )
                    if dispatch_result.sources:
                        sources.extend(dispatch_result.sources)
                except Exception as exc:
                    logger.exception(
                        "Tool execution failed session=%s tool=%s call_id=%s error=%s",
                        masked_session_id,
                        tool_name,
                        call_id,
                        format_exception(exc),
                    )
                    tools_enabled_for_turn = False
                    output_text = (
                        f"Tool '{tool_name}' failed with error: {format_exception(exc)}. "
                        "Proceed without this data and clearly state uncertainty."
                    )

                working_history.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": output_text,
                    }
                )

        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        logger.info("Model call completed session=%s latency_ms=%d", masked_session_id, elapsed_ms)
    except Exception as exc:
        history.pop()
        logger.exception("Model call failed session=%s error=%s", masked_session_id, exc)
        raise HTTPException(
            status_code=502,
            detail=f"Failed to get model response: {exc}",
        ) from exc

    assistant_text = normalize_output_format(assistant_text)
    if not assistant_text:
        assistant_text = "I could not generate a response. Please try again."
        logger.warning("Model returned empty output; fallback message used session=%s", masked_session_id)
    history.append({"role": "assistant", "content": assistant_text})
    pre_trim_count = len(history)
    trimmed_history = trim_history(history)
    conversation_store[payload.session_id] = trimmed_history

    usage = usage_totals or None
    if usage:
        logger.info(
            "Usage session=%s input_tokens=%s output_tokens=%s total_tokens=%s",
            masked_session_id,
            usage.get("input_tokens"),
            usage.get("output_tokens"),
            usage.get("total_tokens"),
        )
    if len(trimmed_history) < pre_trim_count:
        logger.debug(
            "History trimmed session=%s before=%d after=%d",
            masked_session_id,
            pre_trim_count,
            len(trimmed_history),
        )
    logger.debug(
        "Assistant reply prepared session=%s reply_chars=%d reply_preview=%r",
        masked_session_id,
        len(assistant_text),
        preview_text(assistant_text),
    )

    return ChatResponse(
        markdown=assistant_text,
        content_type="text/markdown",
        format="markdown",
        model=active_model(),
        usage=usage,
        sources=sources if sources else None,
    )


@app.post("/api/chat/reset", response_model=ResetResponse)
async def reset_chat(payload: ResetRequest) -> ResetResponse:
    logger.info("Chat session reset session=%s", mask_session_id(payload.session_id))
    conversation_store.pop(payload.session_id, None)
    return ResetResponse(ok=True)
