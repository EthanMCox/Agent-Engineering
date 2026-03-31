from __future__ import annotations

import asyncio
import logging
import shlex
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
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

from .settings import AppSettings

logger = logging.getLogger("canvas_study_coach.backend.mcp")
MCPStatus = Literal["disabled", "starting", "ready", "degraded", "error"]


@dataclass(slots=True)
class MCPHealth:
    enabled: bool
    connected: bool
    status: MCPStatus
    last_error: str | None = None


class CanvasMCPClient:
    def __init__(self, settings: AppSettings) -> None:
        self._enabled = settings.canvas_mcp_enabled
        self._startup_timeout = settings.canvas_mcp_startup_timeout_seconds
        self._call_timeout = settings.canvas_mcp_call_timeout_seconds
        self._command = settings.canvas_mcp_command
        self._cwd = self._resolve_mcp_cwd(settings.canvas_mcp_workdir)
        self._domain = settings.canvas_domain
        self._token = settings.canvas_api_token
        self._lock = asyncio.Lock()
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._last_error: str | None = None
        self._status: MCPStatus = "disabled" if not self._enabled else "starting"

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _resolve_mcp_cwd(self, configured: str) -> str:
        path = Path(configured)
        if path.is_absolute():
            return str(path)
        return str((Path(__file__).resolve().parent.parent / path).resolve())

    def _validate_configuration(self) -> str | None:
        if not self._enabled:
            return None
        if not self._token:
            return "CANVAS_API_TOKEN is required when CANVAS_MCP_ENABLED=true."
        if not self._domain:
            return "CANVAS_DOMAIN is required when CANVAS_MCP_ENABLED=true."
        return None

    def startup_summary(self) -> dict[str, str]:
        return {
            "enabled": str(self._enabled).lower(),
            "command": self._command,
            "workdir": self._cwd,
            "status": self._status,
        }

    def _build_server_parameters(self) -> StdioServerParameters:
        parts = shlex.split(self._command, posix=False)
        if not parts:
            raise RuntimeError("CANVAS_MCP_COMMAND produced an empty command.")

        command = parts[0]
        args = parts[1:]
        env = {
            "CANVAS_API_TOKEN": self._token or "",
            "CANVAS_DOMAIN": self._domain or "",
        }

        return StdioServerParameters(command=command, args=args, env=env, cwd=self._cwd)

    async def start(self) -> None:
        if not self._enabled:
            logger.info("Canvas MCP is disabled (CANVAS_MCP_ENABLED=false).")
            self._status = "disabled"
            return
        if MCP_IMPORT_ERROR is not None:
            self._last_error = f"Python package 'mcp' not installed: {MCP_IMPORT_ERROR}"
            self._status = "error"
            raise RuntimeError(self._last_error)
        validation_error = self._validate_configuration()
        if validation_error:
            self._last_error = validation_error
            self._status = "error"
            raise RuntimeError(validation_error)

        async with self._lock:
            if self._session is not None:
                return
            self._status = "starting"
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
            self._status = "ready"
            await self._probe_tools_locked()
            logger.info("Canvas MCP session initialized command=%s cwd=%s", self._command, self._cwd)
        except Exception as exc:
            await stack.aclose()
            self._session = None
            self._stack = None
            self._last_error = str(exc)
            self._status = "error"
            logger.exception("Failed to initialize Canvas MCP session: %s", exc)
            raise

    async def _probe_tools_locked(self) -> None:
        if self._session is None:
            return
        try:
            async with asyncio.timeout(self._call_timeout):
                await self._session.list_tools()
            self._status = "ready"
        except Exception as exc:
            self._last_error = f"MCP startup probe failed: {exc}"
            self._status = "degraded"
            logger.warning("Canvas MCP initialized but probe failed: %s", exc)

    async def stop(self) -> None:
        async with self._lock:
            await self._stop_locked()

    async def _stop_locked(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self._session = None
        self._status = "disabled" if not self._enabled else "degraded"

    async def health(self) -> MCPHealth:
        return MCPHealth(
            enabled=self._enabled,
            connected=self._session is not None,
            status=self._status,
            last_error=self._last_error,
        )

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
        async with asyncio.timeout(self._call_timeout):
            response = await session.list_tools()
        return [tool.name for tool in response.tools]

    async def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> Any:
        payload = arguments or {}

        for attempt in range(2):
            session = await self._ensure_session()
            try:
                async with asyncio.timeout(self._call_timeout):
                    result = await session.call_tool(tool_name, payload)
                self._status = "ready"
                return result
            except Exception as exc:
                self._last_error = f"{tool_name}: {exc}"
                self._status = "degraded"
                if attempt == 1:
                    self._status = "error"
                    raise
                logger.warning("Canvas MCP call failed; restarting session and retrying tool=%s error=%s", tool_name, exc)
                async with self._lock:
                    await self._stop_locked()
                    self._status = "starting"
                    await self._start_locked()
        raise RuntimeError(f"Unexpected tool retry failure for {tool_name}")

    async def list_courses(self) -> Any:
        return await self.call_tool("list_courses", {})

    async def list_assignments(self, course_id: int | str, limit: int = 20) -> Any:
        return await self.call_tool("list_assignments", {"course_id": int(course_id), "limit": int(limit)})
