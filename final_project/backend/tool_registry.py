from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from .mcp_client import CanvasMCPClient
from .mcp_client import MCPHealth
from .settings import AppSettings

logger = logging.getLogger("canvas_study_coach.backend.tool_registry")


@dataclass(slots=True)
class ToolDispatchResult:
    output_text: str
    sources: list[dict[str, str]]
    error: str | None = None


class CanvasToolRegistry:
    def __init__(self, mcp_client: CanvasMCPClient, settings: AppSettings):
        self._mcp_client = mcp_client
        self._settings = settings

    async def get_openai_tools(self) -> tuple[list[dict[str, Any]], str | None]:
        health = await self._mcp_client.health()
        if not self._can_use_tools(health):
            reason = self._unavailable_reason(health)
            logger.info("Canvas tool registration skipped: %s", reason)
            return [], reason

        try:
            mcp_tools = await self._mcp_client.list_tool_definitions()
        except Exception as exc:
            reason = f"unable to list MCP tools: {self._format_exception(exc)}"
            logger.warning("Canvas tool registration failed: %s", reason)
            return [], reason

        openai_tools: list[dict[str, Any]] = []
        for tool in mcp_tools:
            schema = self._normalize_input_schema(tool.get("input_schema"))
            openai_tools.append(
                {
                    "type": "function",
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": schema,
                    # MCP tool schemas can include optional properties not listed in
                    # required. Avoid strict mode so OpenAI accepts these schemas.
                    "strict": False,
                }
            )
        return openai_tools, None

    @staticmethod
    def _can_use_tools(health: MCPHealth) -> bool:
        return health.enabled and health.status in {"ready", "starting", "degraded"}

    @staticmethod
    def _unavailable_reason(health: MCPHealth) -> str:
        if not health.enabled:
            return "disabled by configuration"
        if health.last_error:
            return f"unavailable ({health.status}): {health.last_error}"
        return f"unavailable ({health.status})"

    @staticmethod
    def _normalize_input_schema(schema: Any) -> dict[str, Any]:
        if not isinstance(schema, dict):
            return {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            }

        normalized = dict(schema)
        if normalized.get("type") != "object":
            normalized = {
                "type": "object",
                "properties": {},
                "required": [],
            }
        normalized.setdefault("properties", {})
        normalized.setdefault("required", [])
        normalized.setdefault("additionalProperties", False)
        return normalized

    @staticmethod
    def _format_exception(exc: Exception) -> str:
        detail = str(exc).strip()
        if detail:
            return f"{type(exc).__name__}: {detail}"
        return type(exc).__name__

    async def dispatch_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> ToolDispatchResult:
        payload = dict(arguments)
        if "limit" in payload:
            try:
                payload["limit"] = max(1, int(payload["limit"]))
            except (TypeError, ValueError):
                payload["limit"] = self._settings.canvas_mcp_assignments_limit

        logger.info(
            "Dispatching Canvas MCP tool=%s payload_keys=%s",
            tool_name,
            sorted(payload.keys()),
        )

        tool_result = await self._mcp_client.call_tool(tool_name, payload)
        logger.info(
            "Canvas MCP tool result received tool=%s structured=%s content_items=%s",
            tool_name,
            getattr(tool_result, "structured_content", None) is not None,
            len(getattr(tool_result, "content", []) or []) if isinstance(getattr(tool_result, "content", None), list) else 0,
        )
        output_text = self._render_tool_result(tool_name, tool_result)
        return ToolDispatchResult(
            output_text=output_text,
            sources=[
                self._source(
                    "canvas_tool",
                    tool_name,
                    f"Canvas tool: {tool_name}",
                    f"Data fetched from Canvas MCP tool '{tool_name}'.",
                )
            ],
        )

    @staticmethod
    def _source(source_type: str, source_id: str, label: str, details: str) -> dict[str, str]:
        return {
            "source_type": source_type,
            "source_id": source_id,
            "label": label,
            "details": details,
        }

    def _render_tool_result(self, tool_name: str, tool_result: Any) -> str:
        structured = getattr(tool_result, "structured_content", None)
        if structured is not None:
            try:
                rendered = json.dumps(structured, indent=2, sort_keys=True, default=str)
            except TypeError:
                rendered = str(structured)
            return f"Canvas MCP tool result ({tool_name}):\n{rendered}"

        content = getattr(tool_result, "content", None)
        if isinstance(content, list):
            lines: list[str] = []
            for item in content:
                text = getattr(item, "text", None)
                if text:
                    lines.append(str(text).strip())
                else:
                    lines.append(str(item))
            if lines:
                return f"Canvas MCP tool result ({tool_name}):\n" + "\n".join(lines)

        return f"Canvas MCP tool result ({tool_name}):\n{tool_result}"


def parse_tool_arguments(arguments_text: str) -> dict[str, Any]:
    if not arguments_text.strip():
        return {}
    try:
        parsed = json.loads(arguments_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Tool arguments must be valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Tool arguments JSON must be an object.")
    return parsed

