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
    context_max_input_tokens: int
    context_reserved_output_tokens: int
    context_reserved_system_tokens: int
    tool_result_max_tokens_per_append: int
    pagination_default_page_size: int
    pagination_max_page_size: int
    pagination_cache_ttl_seconds: int
    pagination_max_results_per_session: int
    openai_summarizer_max_output_tokens: int
    mcp_tool_mode: str
    mcp_tool_profile: str
    mcp_tool_denylist: list[str]
    mcp_tool_allowlist: list[str]
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
    tool_mode = str(raw.get("MCP_TOOL_MODE", "denylist")).strip().lower()
    if tool_mode not in {"denylist", "allowlist"}:
        tool_mode = "denylist"
    tool_profile = str(raw.get("MCP_TOOL_PROFILE", "student")).strip().lower()

    denylist_raw = str(
        raw.get(
            "MCP_TOOL_DENYLIST",
            (
                "canvas_create_course,canvas_update_course,canvas_create_assignment,canvas_update_assignment,"
                "canvas_submit_grade,canvas_enroll_user,canvas_create_quiz,canvas_create_user,"
                "canvas_list_account_users,canvas_list_account_courses,canvas_get_account,"
                "canvas_create_account_report,canvas_get_account_reports,canvas_list_sub_accounts"
            ),
        )
    )
    allowlist_raw = str(raw.get("MCP_TOOL_ALLOWLIST", ""))
    denylist = [item.strip() for item in denylist_raw.split(",") if item.strip()]
    allowlist = [item.strip() for item in allowlist_raw.split(",") if item.strip()]

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
        context_max_input_tokens=max(8000, _to_int(raw.get("CONTEXT_MAX_INPUT_TOKENS"), default=220000)),
        context_reserved_output_tokens=max(512, _to_int(raw.get("CONTEXT_RESERVED_OUTPUT_TOKENS"), default=24000)),
        context_reserved_system_tokens=max(512, _to_int(raw.get("CONTEXT_RESERVED_SYSTEM_TOKENS"), default=6000)),
        tool_result_max_tokens_per_append=max(256, _to_int(raw.get("TOOL_RESULT_MAX_TOKENS_PER_APPEND"), default=12000)),
        pagination_default_page_size=max(5, _to_int(raw.get("PAGINATION_DEFAULT_PAGE_SIZE"), default=30)),
        pagination_max_page_size=max(10, _to_int(raw.get("PAGINATION_MAX_PAGE_SIZE"), default=100)),
        pagination_cache_ttl_seconds=max(60, _to_int(raw.get("PAGINATION_CACHE_TTL_SECONDS"), default=900)),
        pagination_max_results_per_session=max(2, _to_int(raw.get("PAGINATION_MAX_RESULTS_PER_SESSION"), default=16)),
        openai_summarizer_max_output_tokens=max(
            256, _to_int(raw.get("OPENAI_SUMMARIZER_MAX_OUTPUT_TOKENS"), default=800)
        ),
        mcp_tool_mode=tool_mode,
        mcp_tool_profile=tool_profile,
        mcp_tool_denylist=denylist,
        mcp_tool_allowlist=allowlist,
        canvas_domain=str(canvas_domain) if canvas_domain else None,
        canvas_api_token=raw.get("CANVAS_API_TOKEN"),
    )


def load_settings() -> AppSettings:
    return build_settings(load_raw_settings())
