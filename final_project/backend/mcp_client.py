from __future__ import annotations

import asyncio
import logging
import shlex
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from typing import Any
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp import ClientSession as MCPClientSession
    from mcp import StdioServerParameters as MCPStdioServerParameters
else:
    MCPClientSession = Any
    MCPStdioServerParameters = Any

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
        self._call_lock = asyncio.Lock()
        self._stack: AsyncExitStack | None = None
        self._session: MCPClientSession | None = None
        self._last_error: str | None = None
        self._status: MCPStatus = "disabled" if not self._enabled else "starting"
        self._recovery_cooldown_seconds = 15.0
        self._cooldown_until = 0.0

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

    @staticmethod
    def _format_exception(exc: Exception) -> str:
        detail = str(exc).strip()
        if detail:
            return f"{type(exc).__name__}: {detail}"
        return type(exc).__name__

    def _is_transport_recoverable_error(self, exc: Exception) -> bool:
        message = self._format_exception(exc).lower()
        transport_markers = (
            "timeout",
            "cancel",
            "taskgroup",
            "transport",
            "connection",
            "broken pipe",
            "eof",
            "closed resource",
            "stream",
        )
        if any(marker in message for marker in transport_markers):
            return True

        # Some runtimes provide little detail; treat asyncio timeout/cancel types as recoverable.
        return isinstance(exc, (asyncio.TimeoutError, TimeoutError, asyncio.CancelledError))

    def _set_recovery_cooldown(self) -> None:
        loop = asyncio.get_running_loop()
        self._cooldown_until = loop.time() + self._recovery_cooldown_seconds

    def _seconds_until_recovery(self) -> float:
        loop = asyncio.get_running_loop()
        remaining = self._cooldown_until - loop.time()
        return max(0.0, remaining)

    def _build_server_parameters(self) -> MCPStdioServerParameters:
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
            self._last_error = self._format_exception(exc)
            self._status = "error"
            logger.exception("Failed to initialize Canvas MCP session: %s", self._last_error)
            raise

    async def _probe_tools_locked(self) -> None:
        if self._session is None:
            return
        try:
            async with asyncio.timeout(self._call_timeout):
                await self._session.list_tools()
            self._status = "ready"
        except Exception as exc:
            self._last_error = f"MCP startup probe failed: {self._format_exception(exc)}"
            self._status = "error"
            logger.warning("Canvas MCP initialized but probe failed: %s", self._last_error)

    async def stop(self) -> None:
        async with self._call_lock:
            async with self._lock:
                await self._stop_locked()

    async def _stop_locked(self) -> None:
        if self._stack is not None:
            try:
                await self._stack.aclose()
            except Exception as exc:
                # Some MCP transport failures can leave cancellation scopes in an
                # inconsistent state. Force-reset local handles so the client can
                # start a fresh session on the next attempt.
                self._last_error = f"MCP stack close failed during reset: {self._format_exception(exc)}"
                logger.warning("Canvas MCP stack close failed during reset: %s", self._last_error)
        self._stack = None
        self._session = None
        self._status = "disabled"

    async def health(self) -> MCPHealth:
        return MCPHealth(
            enabled=self._enabled,
            connected=self._session is not None,
            status=self._status,
            last_error=self._last_error,
        )

    async def _ensure_session(self) -> MCPClientSession:
        if not self._enabled:
            raise RuntimeError("Canvas MCP is disabled.")

        remaining = self._seconds_until_recovery()
        if remaining > 0:
            reason = self._last_error or "recent MCP transport failure"
            raise RuntimeError(f"Canvas MCP temporarily unavailable for {remaining:.1f}s: {reason}")

        # Clear stale transient errors once cooldown has elapsed so failures do not
        # linger as durable state across subsequent requests.
        if self._session is not None and self._status == "ready":
            self._last_error = None

        if self._session is None:
            await self.start()
        if self._session is None:
            raise RuntimeError("Canvas MCP session is not available.")
        return self._session

    async def list_tools(self) -> list[str]:
        session = await self._ensure_session()
        try:
            async with self._call_lock:
                async with asyncio.timeout(self._call_timeout):
                    response = await session.list_tools()
            self._status = "ready"
            self._last_error = None
            return [getattr(tool, "name", "") for tool in response.tools]
        except Exception as exc:
            formatted_error = self._format_exception(exc)
            self._status = "ready" if self._session is not None else "error"
            self._last_error = f"list_tools: {formatted_error}"
            if self._is_transport_recoverable_error(exc):
                self._set_recovery_cooldown()
            raise

    async def list_tool_definitions(self) -> list[dict[str, Any]]:
        session = await self._ensure_session()
        try:
            async with self._call_lock:
                async with asyncio.timeout(self._call_timeout):
                    response = await session.list_tools()
            self._status = "ready"
            self._last_error = None
        except Exception as exc:
            formatted_error = self._format_exception(exc)
            self._status = "ready" if self._session is not None else "error"
            self._last_error = f"list_tool_definitions: {formatted_error}"
            if self._is_transport_recoverable_error(exc):
                self._set_recovery_cooldown()
            raise

        definitions: list[dict[str, Any]] = []
        for tool in response.tools:
            name = getattr(tool, "name", "")
            if not name:
                continue
            description = str(getattr(tool, "description", "") or "")
            input_schema = (
                getattr(tool, "inputSchema", None)
                or getattr(tool, "input_schema", None)
                or {"type": "object", "properties": {}, "required": []}
            )
            if not isinstance(input_schema, dict):
                input_schema = {"type": "object", "properties": {}, "required": []}
            definitions.append(
                {
                    "name": name,
                    "description": description,
                    "input_schema": input_schema,
                }
            )
        return definitions

    async def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> Any:
        payload = arguments or {}
        session = await self._ensure_session()
        try:
            logger.info(
                "Canvas MCP call attempt tool=%s attempt=%d timeout_seconds=%.1f payload_keys=%s",
                tool_name,
                1,
                self._call_timeout,
                sorted(payload.keys()),
            )
            async with self._call_lock:
                async with asyncio.timeout(self._call_timeout):
                    result = await session.call_tool(tool_name, payload)
            self._status = "ready"
            self._last_error = None
            return result
        except Exception as exc:
            formatted_error = self._format_exception(exc)
            self._last_error = f"{tool_name}: {formatted_error}"
            self._status = "ready" if self._session is not None else "error"

            if self._is_transport_recoverable_error(exc):
                self._set_recovery_cooldown()
                logger.exception(
                    "Canvas MCP call failed; entering cooldown tool=%s payload_keys=%s cooldown_seconds=%.1f error=%s",
                    tool_name,
                    sorted(payload.keys()),
                    self._recovery_cooldown_seconds,
                    formatted_error,
                )
            else:
                logger.warning(
                    "Canvas MCP call failed with non-recoverable error tool=%s payload_keys=%s error=%s",
                    tool_name,
                    sorted(payload.keys()),
                    formatted_error,
                )
            raise

    async def list_courses(self) -> Any:
        return await self.call_tool("list_courses", {})

    async def list_assignments(self, course_id: int | str, limit: int = 20) -> Any:
        return await self.call_tool("list_assignments", {"course_id": int(course_id), "limit": int(limit)})
