from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .context_budget import ContextBudgetPlan
from .mcp_response_middleware import MCPResponseMiddleware
from .settings import AppSettings
from .temporal_context import DEFAULT_TIMEZONE, infer_timeframe_context

logger = logging.getLogger("canvas_study_coach.backend.tool_registry")

SummarizeFunc = Callable[[str, str, int], Awaitable[str]]

LOCAL_TOOL_NAMES = {
    "canvas_query_tool",
    "canvas_get_result_page",
    "canvas_get_result_head",
    "canvas_release_result",
    "canvas_resolve_timeframe",
}

HIGH_VOLUME_TOOLS = {
    "canvas_list_assignments",
    "list_assignments",
    "canvas_list_files",
    "list_files",
}

PROFILE_DENYLISTS: dict[str, set[str]] = {
    "student": {
        "canvas_create_course",
        "canvas_update_course",
        "canvas_create_assignment",
        "canvas_update_assignment",
        "canvas_submit_grade",
        "canvas_enroll_user",
        "canvas_create_quiz",
        "canvas_create_user",
        "canvas_list_account_users",
        "canvas_list_account_courses",
        "canvas_get_account",
        "canvas_create_account_report",
        "canvas_get_account_reports",
        "canvas_list_sub_accounts",
    },
    "instructor": {
        "canvas_create_user",
        "canvas_list_account_users",
        "canvas_list_account_courses",
        "canvas_get_account",
        "canvas_create_account_report",
        "canvas_get_account_reports",
        "canvas_list_sub_accounts",
    },
    "admin": set(),
}


@dataclass(slots=True)
class ToolDispatchResult:
    output_text: str
    sources: list[dict[str, str]]


@dataclass(slots=True)
class _PaginatedResultHandle:
    result_id: str
    session_id: str
    tool_name: str
    args: dict[str, Any]
    created_at: float
    ttl_seconds: int
    items: list[Any]
    raw_payload: Any


class CanvasToolRegistry:
    def __init__(self, mcp_client: Any, settings: AppSettings) -> None:
        self._mcp_client = mcp_client
        self._settings = settings
        self._response_middleware = MCPResponseMiddleware(settings)
        self._tool_definitions: dict[str, dict[str, Any]] = {}
        self._results_by_session: dict[str, dict[str, _PaginatedResultHandle]] = {}

    async def get_openai_tools(self) -> tuple[list[dict[str, Any]], str | None]:
        health = await self._mcp_client.health()
        if not health.enabled:
            return [], "Canvas MCP is disabled by config (CANVAS_MCP_ENABLED=false)."
        if health.status == "disabled":
            reason = f"Canvas MCP status is {health.status}."
            if health.last_error:
                reason = f"{reason} {health.last_error}"
            return [], reason

        try:
            definitions = await self._mcp_client.list_tool_definitions()
        except Exception as exc:
            return [], f"Unable to load MCP tools: {type(exc).__name__}: {exc}"

        filtered = [d for d in definitions if self._is_tool_enabled(d.get("name", ""))]
        self._tool_definitions = {str(d.get("name", "")): d for d in filtered if d.get("name")}
        tools = [self._definition_to_openai_tool(d) for d in filtered]
        tools.extend(self._local_tools())
        return tools, None

    async def dispatch_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        session_id: str,
        user_question: str,
        budget_plan: ContextBudgetPlan,
        current_prompt_tokens: int,
        summarize_func: SummarizeFunc | None,
    ) -> ToolDispatchResult:
        if tool_name == "canvas_query_tool":
            return await self._dispatch_canvas_query_tool(
                arguments,
                session_id=session_id,
                user_question=user_question,
                budget_plan=budget_plan,
                current_prompt_tokens=current_prompt_tokens,
                summarize_func=summarize_func,
            )
        if tool_name == "canvas_get_result_page":
            return await self._dispatch_get_result_page(
                arguments,
                session_id=session_id,
                user_question=user_question,
                budget_plan=budget_plan,
                current_prompt_tokens=current_prompt_tokens,
                summarize_func=summarize_func,
            )
        if tool_name == "canvas_get_result_head":
            return await self._dispatch_get_result_head(
                arguments,
                session_id=session_id,
                user_question=user_question,
                budget_plan=budget_plan,
                current_prompt_tokens=current_prompt_tokens,
                summarize_func=summarize_func,
            )
        if tool_name == "canvas_release_result":
            return self._dispatch_release_result(arguments, session_id=session_id)
        if tool_name == "canvas_resolve_timeframe":
            return await self._dispatch_resolve_timeframe(
                arguments,
                user_question=user_question,
                budget_plan=budget_plan,
                current_prompt_tokens=current_prompt_tokens,
                summarize_func=summarize_func,
            )

        if not self._is_tool_enabled(tool_name):
            raise ValueError(f"Tool '{tool_name}' is disabled by MCP tool governance policy.")

        return await self._execute_canvas_tool_with_mediation(
            tool_name,
            arguments,
            session_id=session_id,
            user_question=user_question,
            budget_plan=budget_plan,
            current_prompt_tokens=current_prompt_tokens,
            summarize_func=summarize_func,
            force_paginate=self._should_force_paginate(tool_name, arguments),
        )

    async def _dispatch_canvas_query_tool(
        self,
        arguments: dict[str, Any],
        *,
        session_id: str,
        user_question: str,
        budget_plan: ContextBudgetPlan,
        current_prompt_tokens: int,
        summarize_func: SummarizeFunc | None,
    ) -> ToolDispatchResult:
        tool_name = str(arguments.get("tool_name", "")).strip()
        if not tool_name:
            raise ValueError("canvas_query_tool requires 'tool_name'.")
        if not self._is_tool_enabled(tool_name):
            raise ValueError(f"Tool '{tool_name}' is disabled by MCP tool governance policy.")

        if "args" not in arguments or not isinstance(arguments.get("args"), dict):
            raise ValueError("canvas_query_tool requires 'args' as an object for wrapped tool arguments.")
        wrapped_args: dict[str, Any] = dict(arguments.get("args") or {})

        self._validate_required_args(tool_name, wrapped_args)
        return await self._execute_canvas_tool_with_mediation(
            tool_name,
            wrapped_args,
            session_id=session_id,
            user_question=user_question,
            budget_plan=budget_plan,
            current_prompt_tokens=current_prompt_tokens,
            summarize_func=summarize_func,
            force_paginate=self._should_force_paginate(tool_name, wrapped_args),
        )

    async def _dispatch_get_result_page(
        self,
        arguments: dict[str, Any],
        *,
        session_id: str,
        user_question: str,
        budget_plan: ContextBudgetPlan,
        current_prompt_tokens: int,
        summarize_func: SummarizeFunc | None,
    ) -> ToolDispatchResult:
        result_id = str(arguments.get("result_id", "")).strip()
        page = max(1, int(arguments.get("page", 1)))
        page_size = int(arguments.get("page_size", self._settings.pagination_default_page_size))
        page_size = max(1, min(page_size, self._settings.pagination_max_page_size))

        handle = self._get_cached_result(session_id, result_id)
        if handle is None:
            raise ValueError(f"Unknown or expired result_id '{result_id}'.")

        return await self._render_cached_page(
            handle,
            page=page,
            page_size=page_size,
            user_question=user_question,
            budget_plan=budget_plan,
            current_prompt_tokens=current_prompt_tokens,
            summarize_func=summarize_func,
        )

    async def _dispatch_get_result_head(
        self,
        arguments: dict[str, Any],
        *,
        session_id: str,
        user_question: str,
        budget_plan: ContextBudgetPlan,
        current_prompt_tokens: int,
        summarize_func: SummarizeFunc | None,
    ) -> ToolDispatchResult:
        result_id = str(arguments.get("result_id", "")).strip()
        top_n = max(1, int(arguments.get("top_n", 5)))
        handle = self._get_cached_result(session_id, result_id)
        if handle is None:
            raise ValueError(f"Unknown or expired result_id '{result_id}'.")

        head_items = handle.items[:top_n]
        synthetic = _PaginatedResultHandle(
            result_id=handle.result_id,
            session_id=handle.session_id,
            tool_name=handle.tool_name,
            args=handle.args,
            created_at=handle.created_at,
            ttl_seconds=handle.ttl_seconds,
            items=head_items,
            raw_payload={"items": head_items},
        )
        return await self._render_cached_page(
            synthetic,
            page=1,
            page_size=max(1, top_n),
            user_question=user_question,
            budget_plan=budget_plan,
            current_prompt_tokens=current_prompt_tokens,
            summarize_func=summarize_func,
        )

    def _dispatch_release_result(self, arguments: dict[str, Any], *, session_id: str) -> ToolDispatchResult:
        result_id = str(arguments.get("result_id", "")).strip()
        session_cache = self._results_by_session.get(session_id, {})
        removed = session_cache.pop(result_id, None)
        if not session_cache and session_id in self._results_by_session:
            self._results_by_session.pop(session_id, None)
        text = f"Released cached Canvas result_id={result_id}." if removed else f"No cached result found for result_id={result_id}."
        return ToolDispatchResult(
            output_text=text,
            sources=[
                {
                    "source_type": "canvas_tool",
                    "source_id": "canvas_release_result",
                    "label": "Canvas cached result release",
                    "details": text,
                }
            ],
        )

    async def _dispatch_resolve_timeframe(
        self,
        arguments: dict[str, Any],
        *,
        user_question: str,
        budget_plan: ContextBudgetPlan,
        current_prompt_tokens: int,
        summarize_func: SummarizeFunc | None,
    ) -> ToolDispatchResult:
        query = str(arguments.get("query", "")).strip() or user_question
        reference_date = str(arguments.get("reference_date", "")).strip() or None
        timezone = str(arguments.get("timezone", DEFAULT_TIMEZONE)).strip() or DEFAULT_TIMEZONE
        payload = infer_timeframe_context(
            query=query,
            reference_date_value=reference_date,
            timezone=timezone,
        )
        return await self._render_payload(
            tool_name="canvas_resolve_timeframe",
            payload=payload,
            user_question=user_question,
            budget_plan=budget_plan,
            current_prompt_tokens=current_prompt_tokens,
            summarize_func=summarize_func,
            source_details="Deterministic academic timeframe inference using local date context.",
            provenance={"timeframe_query": query},
        )

    async def _execute_canvas_tool_with_mediation(
        self,
        tool_name: str,
        args: dict[str, Any],
        *,
        session_id: str,
        user_question: str,
        budget_plan: ContextBudgetPlan,
        current_prompt_tokens: int,
        summarize_func: SummarizeFunc | None,
        force_paginate: bool,
    ) -> ToolDispatchResult:
        logger.info("Dispatching Canvas MCP tool=%s payload_keys=%s", tool_name, sorted(args.keys()))
        raw_result = await self._mcp_client.call_tool(tool_name, args)
        raw_payload = self._extract_payload(raw_result)

        items = self._extract_items_for_pagination(raw_payload)
        if force_paginate:
            handle = self._cache_result(
                session_id=session_id,
                tool_name=tool_name,
                args=args,
                items=items,
                raw_payload=raw_payload,
            )
            return await self._render_cached_page(
                handle,
                page=1,
                page_size=self._settings.pagination_default_page_size,
                user_question=user_question,
                budget_plan=budget_plan,
                current_prompt_tokens=current_prompt_tokens,
                summarize_func=summarize_func,
            )

        return await self._render_payload(
            tool_name=tool_name,
            payload=raw_payload,
            user_question=user_question,
            budget_plan=budget_plan,
            current_prompt_tokens=current_prompt_tokens,
            summarize_func=summarize_func,
            source_details=f"Data fetched from Canvas MCP {tool_name}.",
        )

    async def _render_cached_page(
        self,
        handle: _PaginatedResultHandle,
        *,
        page: int,
        page_size: int,
        user_question: str,
        budget_plan: ContextBudgetPlan,
        current_prompt_tokens: int,
        summarize_func: SummarizeFunc | None,
    ) -> ToolDispatchResult:
        total_items = len(handle.items)
        if total_items == 0:
            page_count = 1
            page = 1
            page_items: list[Any] = []
        else:
            page_count = max(1, (total_items + page_size - 1) // page_size)
            page = max(1, min(page, page_count))
            start = (page - 1) * page_size
            end = min(total_items, start + page_size)
            page_items = handle.items[start:end]

        payload = {
            "result_id": handle.result_id,
            "tool_name": handle.tool_name,
            "args": handle.args,
            "page": page,
            "page_size": page_size,
            "page_count": page_count,
            "total_items": total_items,
            "items": page_items,
        }
        rendered = await self._render_payload(
            tool_name=handle.tool_name,
            payload=payload,
            user_question=user_question,
            budget_plan=budget_plan,
            current_prompt_tokens=current_prompt_tokens,
            summarize_func=summarize_func,
            source_details=f"Paginated Canvas MCP result_id={handle.result_id} page={page}/{page_count} from {handle.tool_name}.",
            pagination={
                "result_id": handle.result_id,
                "page": page,
                "page_size": page_size,
                "page_count": page_count,
                "total_items": total_items,
            },
            provenance={
                "pagination_mode": True,
            },
        )
        return rendered

    async def _render_payload(
        self,
        *,
        tool_name: str,
        payload: Any,
        user_question: str,
        budget_plan: ContextBudgetPlan,
        current_prompt_tokens: int,
        summarize_func: SummarizeFunc | None,
        source_details: str,
        pagination: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> ToolDispatchResult:
        middleware_result = await self._response_middleware.process(
            tool_name=tool_name,
            raw_payload=payload,
            user_question=user_question,
            budget_plan=budget_plan,
            current_prompt_tokens=current_prompt_tokens,
            summarize_func=summarize_func,
            pagination=pagination,
            provenance=provenance or {},
        )
        output_text = middleware_result.serialized_output
        return ToolDispatchResult(
            output_text=output_text,
            sources=[
                {
                    "source_type": "canvas_tool",
                    "source_id": tool_name,
                    "label": f"Canvas tool {tool_name}",
                    "details": source_details,
                }
            ],
        )

    def _extract_payload(self, raw_result: Any) -> Any:
        structured = getattr(raw_result, "structured_content", None)
        if structured is not None:
            return structured

        content = getattr(raw_result, "content", None)
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                text = getattr(item, "text", None)
                if text is None and isinstance(item, dict):
                    text = item.get("text")
                if text:
                    parts.append(str(text))
            joined = "\n".join(parts).strip()
            if not joined:
                return {}
            try:
                return json.loads(joined)
            except Exception:
                return {"text": joined}

        text = str(raw_result).strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except Exception:
            return {"text": text}

    def _extract_items_for_pagination(self, payload: Any) -> list[Any]:
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("items", "assignments", "courses", "files", "rubrics", "modules"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
            return [payload]
        return [payload]

    def _cache_result(
        self,
        *,
        session_id: str,
        tool_name: str,
        args: dict[str, Any],
        items: list[Any],
        raw_payload: Any,
    ) -> _PaginatedResultHandle:
        session_cache = self._results_by_session.setdefault(session_id, {})
        self._prune_session_cache(session_id)

        result_id = uuid.uuid4().hex[:12]
        handle = _PaginatedResultHandle(
            result_id=result_id,
            session_id=session_id,
            tool_name=tool_name,
            args=args,
            created_at=time.time(),
            ttl_seconds=self._settings.pagination_cache_ttl_seconds,
            items=items,
            raw_payload=raw_payload,
        )
        session_cache[result_id] = handle
        while len(session_cache) > self._settings.pagination_max_results_per_session:
            oldest_id = min(session_cache, key=lambda rid: session_cache[rid].created_at)
            session_cache.pop(oldest_id, None)
        return handle

    def _get_cached_result(self, session_id: str, result_id: str) -> _PaginatedResultHandle | None:
        self._prune_session_cache(session_id)
        session_cache = self._results_by_session.get(session_id, {})
        return session_cache.get(result_id)

    def _prune_session_cache(self, session_id: str) -> None:
        session_cache = self._results_by_session.get(session_id)
        if not session_cache:
            return
        now = time.time()
        expired = [rid for rid, handle in session_cache.items() if now - handle.created_at > handle.ttl_seconds]
        for rid in expired:
            session_cache.pop(rid, None)
        if not session_cache:
            self._results_by_session.pop(session_id, None)

    def _validate_required_args(self, tool_name: str, args: dict[str, Any]) -> None:
        required: list[str] = []
        schema = self._tool_definitions.get(tool_name, {}).get("input_schema", {})
        if isinstance(schema, dict):
            raw_required = schema.get("required", [])
            if isinstance(raw_required, list):
                required = [str(item) for item in raw_required]

        fallback_required = {
            "canvas_get_assignment": ["course_id", "assignment_id"],
            "get_assignment": ["course_id", "assignment_id"],
            "canvas_list_assignments": ["course_id"],
            "list_assignments": ["course_id"],
        }
        if not required:
            required = fallback_required.get(tool_name, [])

        missing = [name for name in required if name not in args]
        if missing:
            raise ValueError(f"canvas_query_tool missing required wrapped args for {tool_name}: {', '.join(missing)}")

    def _should_force_paginate(self, tool_name: str, args: dict[str, Any]) -> bool:
        if tool_name in HIGH_VOLUME_TOOLS:
            if bool(args.get("include_submissions", False)):
                return True
            if tool_name in {"canvas_list_files", "list_files"}:
                return True
        return False

    def _definition_to_openai_tool(self, definition: dict[str, Any]) -> dict[str, Any]:
        schema = definition.get("input_schema", {})
        if not isinstance(schema, dict):
            schema = {}
        if schema.get("type") != "object":
            schema["type"] = "object"
        schema.setdefault("properties", {})
        schema.setdefault("required", [])
        schema["additionalProperties"] = False

        return {
            "type": "function",
            "name": str(definition.get("name", "")),
            "description": str(definition.get("description", "") or "Canvas MCP tool"),
            "parameters": schema,
            "strict": False,
        }

    def _local_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "name": "canvas_query_tool",
                "description": (
                    "Run a Canvas MCP tool via the response middleware. "
                    "Legacy wrapper controls are accepted for backward compatibility but ignored at runtime."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tool_name": {"type": "string"},
                        "args": {"type": "object", "additionalProperties": True},
                        "fields": {"type": "array", "items": {"type": "string"}},
                        "mediation_mode": {"type": "string"},
                        "include_description": {"type": "boolean"},
                        "include_rubric": {"type": "boolean"},
                        "include_attachments": {"type": "boolean"},
                        "include_submission": {"type": "boolean"},
                    },
                    "required": ["tool_name", "args"],
                    "additionalProperties": False,
                },
                "strict": False,
            },
            {
                "type": "function",
                "name": "canvas_get_result_page",
                "description": "Read a paginated page from a previously cached Canvas result.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "result_id": {"type": "string"},
                        "page": {"type": "integer", "minimum": 1},
                        "page_size": {"type": "integer", "minimum": 1},
                    },
                    "required": ["result_id", "page"],
                    "additionalProperties": False,
                },
                "strict": False,
            },
            {
                "type": "function",
                "name": "canvas_get_result_head",
                "description": "Return the first N items from a cached Canvas result.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "result_id": {"type": "string"},
                        "top_n": {"type": "integer", "minimum": 1},
                    },
                    "required": ["result_id"],
                    "additionalProperties": False,
                },
                "strict": False,
            },
            {
                "type": "function",
                "name": "canvas_release_result",
                "description": "Release a cached Canvas pagination result.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "result_id": {"type": "string"},
                    },
                    "required": ["result_id"],
                    "additionalProperties": False,
                },
                "strict": False,
            },
            {
                "type": "function",
                "name": "canvas_resolve_timeframe",
                "description": (
                    "Resolve temporal phrases (for example 'this semester' or 'next term') into likely academic term windows "
                    "using deterministic local-date inference."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "reference_date": {"type": "string"},
                        "timezone": {"type": "string"},
                    },
                    "required": [],
                    "additionalProperties": False,
                },
                "strict": False,
            },
        ]

    def _is_tool_enabled(self, tool_name: str) -> bool:
        name = str(tool_name or "").strip()
        if not name:
            return False
        if name in LOCAL_TOOL_NAMES:
            return True

        mode = self._settings.mcp_tool_mode
        allowlist = {item.strip() for item in self._settings.mcp_tool_allowlist if item.strip()}
        denylist = {item.strip() for item in self._settings.mcp_tool_denylist if item.strip()}
        denylist |= PROFILE_DENYLISTS.get(self._settings.mcp_tool_profile, set())

        if mode == "allowlist":
            return name in allowlist
        return name not in denylist


def parse_tool_arguments(raw_arguments: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_arguments or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"Tool arguments must be valid JSON object: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Tool arguments must decode to a JSON object.")
    return parsed
