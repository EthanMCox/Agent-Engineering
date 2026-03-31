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
