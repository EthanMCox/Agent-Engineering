from __future__ import annotations

import logging
import os
import re
import time
from typing import Any
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

SYSTEM_PROMPT = (
    "You are a helpful study assistant for a student web app. "
    "Be concise, honest, and practical. "
    "If you are unsure, clearly say so instead of making up facts. "
    "Format answers cleanly: use short paragraphs, bullet lists when helpful, and fenced code blocks only when needed. "
    "Output markdown only. Do not output raw HTML, CSS, JavaScript, or inline style attributes. "
    "If a user asks for color/styling that requires CSS, explain that the app controls colors and provide the content in markdown. "
    "You may use markdown formatting such as headings, bold, italics, lists, blockquotes, and inline code."
)
DEFAULT_MODEL = "gpt-5-nano"
MAX_TURNS = 12


def configure_logging() -> logging.Logger:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
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
    reply: str
    content_blocks: list["ContentBlock"]
    format: Literal["markdown", "blocks"] = "markdown"
    model: str
    usage: dict[str, Any] | None = None


class ParagraphBlock(BaseModel):
    type: Literal["paragraph"]
    text: str


class ListBlock(BaseModel):
    type: Literal["list"]
    items: list[str]


class CodeBlock(BaseModel):
    type: Literal["code"]
    language: str
    code: str


class MarkdownBlock(BaseModel):
    type: Literal["markdown"]
    text: str


ContentBlock = ParagraphBlock | ListBlock | CodeBlock | MarkdownBlock


class ResetRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=200)


class ResetResponse(BaseModel):
    ok: bool


class HealthResponse(BaseModel):
    ok: bool
    model: str


app = FastAPI(title="Canvas Study Coach Chat API", version="0.1.0")

allowed_origins = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in allowed_origins.split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

client = AsyncOpenAI()
conversation_store: dict[str, list[dict[str, str]]] = {}


def active_model() -> str:
    return os.getenv("OPENAI_MODEL", DEFAULT_MODEL)


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

    # Avoid rendering raw HTML payloads from model output; keep response markdown-safe.
    if re.search(r"<\s*(?:div|span|p|h[1-6]|ul|ol|li|strong|em|style|script|table)\b", stripped, re.IGNORECASE):
        logger.warning("Model returned HTML-like content; converting response to markdown-safe fallback")
        return (
            "I can format with markdown (headings, bold, italics, lists), "
            "but I cannot directly set text color from the model response.\n\n"
            "### Example\n"
            "- Avocado Toast\n"
            "- **Blueberries**\n"
            "- Quinoa Salad\n"
            "- *Sushi*\n"
            "- Spaghetti Bolognese"
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


def parse_content_blocks(text: str) -> list[ContentBlock]:
    clean_text = text.strip()
    if not clean_text:
        return [ParagraphBlock(type="paragraph", text="I could not generate a response. Please try again.")]

    blocks: list[ContentBlock] = []
    code_pattern = re.compile(r"```([A-Za-z0-9_-]+)?\n(.*?)```", re.DOTALL)
    cursor = 0

    for match in code_pattern.finditer(clean_text):
        pre_code_segment = clean_text[cursor : match.start()]
        _parse_non_code_segment(pre_code_segment, blocks)

        language = (match.group(1) or "text").strip() or "text"
        code = match.group(2).strip("\n")
        blocks.append(CodeBlock(type="code", language=language, code=code))
        cursor = match.end()

    tail_segment = clean_text[cursor:]
    _parse_non_code_segment(tail_segment, blocks)

    if not blocks:
        return [ParagraphBlock(type="paragraph", text=clean_text)]

    return blocks


def _parse_non_code_segment(segment: str, blocks: list[ContentBlock]) -> None:
    normalized = segment.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return

    chunks = re.split(r"\n\s*\n+", normalized)
    for chunk in chunks:
        lines = [line.rstrip() for line in chunk.split("\n") if line.strip()]
        if not lines:
            continue

        if all(_is_list_line(line) for line in lines):
            items = [_strip_list_prefix(line).strip() for line in lines]
            items = [item for item in items if item]
            if items:
                blocks.append(ListBlock(type="list", items=items))
            continue

        paragraph_text = "\n".join(lines).strip()
        if paragraph_text:
            blocks.append(ParagraphBlock(type="paragraph", text=paragraph_text))


def _is_list_line(line: str) -> bool:
    return re.match(r"^\s*(?:[-*]\s+|\d+\.\s+)", line) is not None


def _strip_list_prefix(line: str) -> str:
    return re.sub(r"^\s*(?:[-*]\s+|\d+\.\s+)", "", line)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    logger.debug("Health check requested")
    return HealthResponse(ok=True, model=active_model())


@app.post("/api/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest) -> ChatResponse:
    masked_session_id = mask_session_id(payload.session_id)
    logger.info("Chat request received session=%s message_chars=%d", masked_session_id, len(payload.message))

    if not os.getenv("OPENAI_API_KEY"):
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
        response = await client.responses.create(
            model=selected_model,
            input=history,
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

    assistant_text = normalize_output_format(response.output_text or "")
    if not assistant_text:
        assistant_text = "I could not generate a response. Please try again."
        logger.warning("Model returned empty output; fallback message used session=%s", masked_session_id)
    content_blocks: list[ContentBlock] = [MarkdownBlock(type="markdown", text=assistant_text)]

    history.append({"role": "assistant", "content": assistant_text})
    pre_trim_count = len(history)
    trimmed_history = trim_history(history)
    conversation_store[payload.session_id] = trimmed_history

    usage = response.usage.model_dump() if response.usage else None
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
        reply=assistant_text,
        content_blocks=content_blocks,
        format="markdown",
        model=active_model(),
        usage=usage,
    )


@app.post("/api/chat/reset", response_model=ResetResponse)
async def reset_chat(payload: ResetRequest) -> ResetResponse:
    logger.info("Chat session reset session=%s", mask_session_id(payload.session_id))
    conversation_store.pop(payload.session_id, None)
    return ResetResponse(ok=True)
