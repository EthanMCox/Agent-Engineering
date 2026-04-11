from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import dotenv_values


@dataclass(slots=True)
class AppSettings:
    openai_api_key: str | None
    openai_model: str
    openai_summarizer_model: str
    openai_log_reasoning_summaries: bool
    openai_reasoning_effort: str | None
    cors_origins: list[str]
    log_level: str
    canvas_mcp_enabled: bool
    canvas_mcp_command: str
    canvas_mcp_workdir: str
    canvas_mcp_startup_timeout_seconds: float
    canvas_mcp_call_timeout_seconds: float
    canvas_mcp_course_limit: int
    canvas_mcp_assignments_limit: int
    canvas_domain: str | None
    canvas_api_token: str | None


def _to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _to_float(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _to_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def load_raw_settings() -> dict[str, str]:
    env_map = merge_env_sources(os.environ, {})
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        env_map = merge_env_sources(env_map, dotenv_values(env_path))
    return env_map


def merge_env_sources(base_env: dict[str, str], override_env: dict[str, Any]) -> dict[str, str]:
    merged: dict[str, str] = {k: str(v) for k, v in base_env.items()}
    # .env takes precedence over OS env for shared keys.
    for key, value in override_env.items():
        if value is not None:
            merged[key] = str(value)
    return merged


def build_settings(raw: dict[str, Any]) -> AppSettings:
    cors_raw = str(raw.get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"))
    cors_origins = [origin.strip() for origin in cors_raw.split(",") if origin.strip()]

    canvas_domain = raw.get("CANVAS_DOMAIN") or raw.get("CANVAS_BASE_URL")

    return AppSettings(
        openai_api_key=raw.get("OPENAI_API_KEY"),
        openai_model=str(raw.get("OPENAI_MODEL", "gpt-5-nano")),
        openai_summarizer_model=str(raw.get("OPENAI_SUMMARIZER_MODEL", "gpt-4.1-mini")),
        openai_log_reasoning_summaries=_to_bool(raw.get("OPENAI_LOG_REASONING_SUMMARIES"), default=False),
        openai_reasoning_effort=(str(raw.get("OPENAI_REASONING_EFFORT", "")).strip() or None),
        cors_origins=cors_origins,
        log_level=str(raw.get("LOG_LEVEL", "INFO")),
        canvas_mcp_enabled=_to_bool(raw.get("CANVAS_MCP_ENABLED"), default=False),
        canvas_mcp_command=str(raw.get("CANVAS_MCP_COMMAND", "npx canvas-mcp-server")),
        canvas_mcp_workdir=str(raw.get("CANVAS_MCP_WORKDIR", Path(__file__).resolve().parent.parent / "mcp-canvas")),
        canvas_mcp_startup_timeout_seconds=_to_float(raw.get("CANVAS_MCP_STARTUP_TIMEOUT_SECONDS"), default=15.0),
        canvas_mcp_call_timeout_seconds=_to_float(raw.get("CANVAS_MCP_CALL_TIMEOUT_SECONDS"), default=20.0),
        canvas_mcp_course_limit=max(1, _to_int(raw.get("CANVAS_MCP_COURSE_LIMIT"), default=3)),
        canvas_mcp_assignments_limit=max(1, _to_int(raw.get("CANVAS_MCP_ASSIGNMENTS_LIMIT"), default=8)),
        canvas_domain=str(canvas_domain) if canvas_domain else None,
        canvas_api_token=raw.get("CANVAS_API_TOKEN"),
    )


def load_settings() -> AppSettings:
    return build_settings(load_raw_settings())
