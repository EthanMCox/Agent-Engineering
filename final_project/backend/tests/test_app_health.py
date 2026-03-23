from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app import app
from backend.app import canvas_mcp_client
from backend.mcp_client import MCPHealth


def test_health_reports_mcp_status(monkeypatch) -> None:
    async def fake_health() -> MCPHealth:
        return MCPHealth(enabled=True, connected=True, last_error=None)

    monkeypatch.setattr(canvas_mcp_client, "health", fake_health)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["mcp_canvas_enabled"] is True
    assert payload["mcp_canvas_ok"] is True
