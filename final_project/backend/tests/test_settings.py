from __future__ import annotations

from backend.settings import build_settings
from backend.settings import merge_env_sources


def test_merge_env_sources_prefers_override_values() -> None:
    base = {
        "OPENAI_MODEL": "gpt-5-nano",
        "CANVAS_DOMAIN": "os.example.edu",
    }
    override = {
        "CANVAS_DOMAIN": "dotenv.example.edu",
        "CANVAS_MCP_ENABLED": "true",
    }

    merged = merge_env_sources(base, override)
    assert merged["CANVAS_DOMAIN"] == "dotenv.example.edu"
    assert merged["CANVAS_MCP_ENABLED"] == "true"


def test_build_settings_defaults_and_limits() -> None:
    settings = build_settings(
        {
            "CANVAS_MCP_ENABLED": "true",
            "CANVAS_MCP_COURSE_LIMIT": "0",
            "CANVAS_MCP_ASSIGNMENTS_LIMIT": "-3",
        }
    )

    assert settings.canvas_mcp_enabled is True
    assert settings.canvas_mcp_course_limit == 1
    assert settings.canvas_mcp_assignments_limit == 1
    assert settings.context_max_input_tokens >= 8000
    assert settings.pagination_default_page_size >= 5
    assert settings.mcp_tool_mode in {"denylist", "allowlist"}
    assert settings.mcp_tool_profile == "student"
    assert "canvas_submit_grade" in settings.mcp_tool_denylist
    assert settings.mcp_response_middleware_enabled is True
    assert settings.mcp_response_pass_through_max_tokens >= 512
    assert settings.mcp_response_chunk_target_tokens >= 200
    assert settings.mcp_response_max_chunks >= 1
    assert settings.mcp_response_field_selector_max_fields >= 1
    assert settings.mcp_response_hierarchical_merge_fanin >= 2
    assert settings.mcp_response_llm_timeout_seconds >= 1.0


def test_build_settings_tool_policy_values() -> None:
    settings = build_settings(
        {
            "MCP_TOOL_MODE": "allowlist",
            "MCP_TOOL_PROFILE": "instructor",
            "MCP_TOOL_ALLOWLIST": "canvas_list_courses,canvas_get_assignment",
            "MCP_TOOL_DENYLIST": "canvas_submit_grade",
        }
    )

    assert settings.mcp_tool_mode == "allowlist"
    assert settings.mcp_tool_profile == "instructor"
    assert settings.mcp_tool_allowlist == ["canvas_list_courses", "canvas_get_assignment"]
    assert settings.mcp_tool_denylist == ["canvas_submit_grade"]


def test_build_settings_mcp_response_overrides() -> None:
    settings = build_settings(
        {
            "MCP_RESPONSE_MIDDLEWARE_ENABLED": "false",
            "MCP_RESPONSE_PASS_THROUGH_MAX_TOKENS": "7000",
            "MCP_RESPONSE_CHUNK_TARGET_TOKENS": "1800",
            "MCP_RESPONSE_MAX_CHUNKS": "6",
            "MCP_RESPONSE_FIELD_SELECTOR_MAX_FIELDS": "12",
            "MCP_RESPONSE_HIERARCHICAL_MERGE_FANIN": "5",
            "MCP_RESPONSE_LLM_TIMEOUT_SECONDS": "9.5",
        }
    )

    assert settings.mcp_response_middleware_enabled is False
    assert settings.mcp_response_pass_through_max_tokens == 7000
    assert settings.mcp_response_chunk_target_tokens == 1800
    assert settings.mcp_response_max_chunks == 6
    assert settings.mcp_response_field_selector_max_fields == 12
    assert settings.mcp_response_hierarchical_merge_fanin == 5
    assert settings.mcp_response_llm_timeout_seconds == 9.5
