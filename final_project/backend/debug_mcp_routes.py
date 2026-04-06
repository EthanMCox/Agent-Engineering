from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .mcp_client import CanvasMCPClient
from .tool_registry import CanvasToolRegistry


class MCPToolsResponse(BaseModel):
    ok: bool
    count: int
    tools: list[str]
    error: str | None = None


class MCPToolProbeRequest(BaseModel):
    tool_name: str = Field(min_length=1, max_length=200)
    arguments: dict[str, Any] = Field(default_factory=dict)


class MCPToolProbeResponse(BaseModel):
    ok: bool
    tool_name: str
    elapsed_ms: int
    output_text: str | None = None
    output_chars: int | None = None
    sources: list[dict[str, str]] | None = None
    error: str | None = None


def _format_exception(exc: Exception) -> str:
    detail = str(exc).strip()
    if detail:
        return f"{type(exc).__name__}: {detail}"
    return type(exc).__name__


def create_debug_mcp_router(
    mcp_client: CanvasMCPClient,
    tool_registry: CanvasToolRegistry,
    logger: logging.Logger,
) -> APIRouter:
    router = APIRouter(tags=["debug-mcp"])

    @router.get("/api/debug/mcp/tools", response_model=MCPToolsResponse)
    async def debug_list_mcp_tools() -> MCPToolsResponse:
        start = time.perf_counter()
        try:
            definitions = await mcp_client.list_tool_definitions()
            names = sorted(tool.get("name", "") for tool in definitions if tool.get("name"))
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            logger.info("MCP tool list debug call succeeded tool_count=%d latency_ms=%d", len(names), elapsed_ms)
            return MCPToolsResponse(ok=True, count=len(names), tools=names)
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            error = _format_exception(exc)
            logger.warning("MCP tool list debug call failed latency_ms=%d error=%s", elapsed_ms, error)
            return MCPToolsResponse(ok=False, count=0, tools=[], error=error)

    @router.post("/api/debug/mcp/call", response_model=MCPToolProbeResponse)
    async def debug_call_mcp_tool(payload: MCPToolProbeRequest) -> MCPToolProbeResponse:
        start = time.perf_counter()
        try:
            result = await tool_registry.dispatch_tool_call(payload.tool_name, payload.arguments)
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            logger.info(
                "MCP tool debug call succeeded tool=%s latency_ms=%d output_chars=%d",
                payload.tool_name,
                elapsed_ms,
                len(result.output_text),
            )
            return MCPToolProbeResponse(
                ok=True,
                tool_name=payload.tool_name,
                elapsed_ms=elapsed_ms,
                output_text=result.output_text,
                output_chars=len(result.output_text),
                sources=result.sources,
            )
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            error = _format_exception(exc)
            logger.warning(
                "MCP tool debug call failed tool=%s latency_ms=%d error=%s",
                payload.tool_name,
                elapsed_ms,
                error,
            )
            return MCPToolProbeResponse(
                ok=False,
                tool_name=payload.tool_name,
                elapsed_ms=elapsed_ms,
                error=error,
            )

    return router
