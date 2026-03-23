from __future__ import annotations

import asyncio
import logging
import os
import shlex
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    MCP_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised by import-time env constraints.
    ClientSession = Any  # type: ignore[assignment]
    StdioServerParameters = Any  # type: ignore[assignment]
    stdio_client = None  # type: ignore[assignment]
    MCP_IMPORT_ERROR = exc


logger = logging.getLogger("canvas_study_coach.backend.mcp")


@dataclass(slots=True)
class MCPHealth:
    enabled: bool
    connected: bool
    last_error: str | None = None


class CanvasMCPClient:
    def __init__(self) -> None:
        self._enabled = os.getenv("CANVAS_MCP_ENABLED", "false").lower() == "true"
        self._startup_timeout = float(os.getenv("CANVAS_MCP_STARTUP_TIMEOUT_SECONDS", "15"))
        self._command = os.getenv("CANVAS_MCP_COMMAND", "npx canvas-mcp-server")
        self._cwd = self._resolve_mcp_cwd()
        self._lock = asyncio.Lock()
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._last_error: str | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _resolve_mcp_cwd(self) -> str:
        configured = os.getenv("CANVAS_MCP_WORKDIR")
        if configured:
            return configured
        return str(Path(__file__).resolve().parent.parent / "mcp-canvas")

    def _build_server_parameters(self) -> StdioServerParameters:
        parts = shlex.split(self._command, posix=False)
        if not parts:
            raise RuntimeError("CANVAS_MCP_COMMAND produced an empty command.")

        command = parts[0]
        args = parts[1:]
        env = os.environ.copy()

        # Backward-compatible alias: CANVAS_BASE_URL can populate CANVAS_DOMAIN.
        if env.get("CANVAS_BASE_URL") and not env.get("CANVAS_DOMAIN"):
            env["CANVAS_DOMAIN"] = env["CANVAS_BASE_URL"]

        return StdioServerParameters(command=command, args=args, env=env, cwd=self._cwd)

    async def start(self) -> None:
        if not self._enabled:
            logger.info("Canvas MCP is disabled (CANVAS_MCP_ENABLED=false).")
            return
        if MCP_IMPORT_ERROR is not None:
            self._last_error = f"Python package 'mcp' not installed: {MCP_IMPORT_ERROR}"
            raise RuntimeError(self._last_error)

        async with self._lock:
            if self._session is not None:
                return
            await self._start_locked()

    async def _start_locked(self) -> None:
        stack = AsyncExitStack()
        try:
            server_params = self._build_server_parameters()
            async with asyncio.timeout(self._startup_timeout):
                if stdio_client is None:
                    raise RuntimeError("MCP stdio client is unavailable.")
                read_stream, write_stream = await stack.enter_async_context(stdio_client(server_params))
                session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
                await session.initialize()
            self._stack = stack
            self._session = session
            self._last_error = None
            logger.info("Canvas MCP session initialized command=%s cwd=%s", self._command, self._cwd)
        except Exception as exc:
            await stack.aclose()
            self._session = None
            self._stack = None
            self._last_error = str(exc)
            logger.exception("Failed to initialize Canvas MCP session: %s", exc)
            raise

    async def stop(self) -> None:
        async with self._lock:
            await self._stop_locked()

    async def _stop_locked(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self._session = None

    async def health(self) -> MCPHealth:
        return MCPHealth(enabled=self._enabled, connected=self._session is not None, last_error=self._last_error)

    async def _ensure_session(self) -> ClientSession:
        if not self._enabled:
            raise RuntimeError("Canvas MCP is disabled.")
        if self._session is None:
            await self.start()
        if self._session is None:
            raise RuntimeError("Canvas MCP session is not available.")
        return self._session

    async def list_tools(self) -> list[str]:
        session = await self._ensure_session()
        response = await session.list_tools()
        return [tool.name for tool in response.tools]

    async def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> Any:
        payload = arguments or {}

        for attempt in range(2):
            session = await self._ensure_session()
            try:
                return await session.call_tool(tool_name, payload)
            except Exception as exc:
                self._last_error = f"{tool_name}: {exc}"
                if attempt == 1:
                    raise
                logger.warning("Canvas MCP call failed; restarting session and retrying tool=%s error=%s", tool_name, exc)
                async with self._lock:
                    await self._stop_locked()
                    await self._start_locked()
        raise RuntimeError(f"Unexpected tool retry failure for {tool_name}")

    async def list_courses(self) -> Any:
        return await self.call_tool("list_courses", {})

    async def list_assignments(self, course_id: int | str, limit: int = 20) -> Any:
        return await self.call_tool("list_assignments", {"course_id": int(course_id), "limit": int(limit)})
