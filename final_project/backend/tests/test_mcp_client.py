from __future__ import annotations

import asyncio

import pytest

from backend.mcp_client import CanvasMCPClient
from backend.mcp_client import MCP_IMPORT_ERROR


def test_mcp_client_reports_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("CANVAS_MCP_ENABLED", raising=False)
    client = CanvasMCPClient()
    assert client.enabled is False


def test_mcp_client_start_fails_cleanly_when_enabled_but_missing_dependency(monkeypatch) -> None:
    monkeypatch.setenv("CANVAS_MCP_ENABLED", "true")
    client = CanvasMCPClient()

    if MCP_IMPORT_ERROR is None:
        pytest.skip("mcp is installed in this environment; missing-dependency case not applicable.")

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(client.start())
    assert "mcp" in str(exc_info.value).lower()
