from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .context_budget import ContextBudgetPlan
from .context_budget import estimate_tokens_from_text
from .settings import AppSettings

logger = logging.getLogger("canvas_study_coach.backend.tool_registry")

SummarizeFunc = Callable[[str, str, int], Awaitable[str]]

LOCAL_TOOL_NAMES = {
    "canvas_query_tool",
    "canvas_get_result_page",
    "canvas_get_result_head",
    "canvas_release_result",
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
class _MediationOptions:
    fields: list[str] | None
    mediation_mode: str
    include_description: bool
    include_rubric: bool
    include_attachments: bool
    include_submission: bool


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
    mediation: _MediationOptions


class CanvasToolRegistry:
    def __init__(self, mcp_client: Any, settings: AppSettings) -> None:
        self._mcp_client = mcp_client
        self._settings = settings
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

        if not self._is_tool_enabled(tool_name):
            raise ValueError(f"Tool '{tool_name}' is disabled by MCP tool governance policy.")

        options = self._default_mediation_for_direct_call(tool_name)
        return await self._execute_canvas_tool_with_mediation(
            tool_name,
            arguments,
            session_id=session_id,
            user_question=user_question,
            budget_plan=budget_plan,
            current_prompt_tokens=current_prompt_tokens,
            summarize_func=summarize_func,
            options=options,
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

        options = _MediationOptions(
            fields=[str(item) for item in arguments.get("fields", []) if str(item).strip()] or None,
            mediation_mode=str(arguments.get("mediation_mode", "compact")).strip().lower() or "compact",
            include_description=bool(arguments.get("include_description", False)),
            include_rubric=bool(arguments.get("include_rubric", False)),
            include_attachments=bool(arguments.get("include_attachments", False)),
            include_submission=bool(arguments.get("include_submission", False)),
        )
        if options.mediation_mode not in {"compact", "full_if_fits", "full"}:
            raise ValueError("canvas_query_tool 'mediation_mode' must be one of: compact, full_if_fits, full.")

        self._validate_required_args(tool_name, wrapped_args)
        return await self._execute_canvas_tool_with_mediation(
            tool_name,
            wrapped_args,
            session_id=session_id,
            user_question=user_question,
            budget_plan=budget_plan,
            current_prompt_tokens=current_prompt_tokens,
            summarize_func=summarize_func,
            options=options,
            force_paginate=True,
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
            mediation=handle.mediation,
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
        options: _MediationOptions,
        force_paginate: bool,
    ) -> ToolDispatchResult:
        logger.info("Dispatching Canvas MCP tool=%s payload_keys=%s", tool_name, sorted(args.keys()))
        raw_result = await self._mcp_client.call_tool(tool_name, args)
        raw_payload = self._extract_payload(raw_result)

        items = self._extract_items_for_pagination(raw_payload)
        if force_paginate or self._estimated_payload_tokens(raw_payload) > self._settings.tool_result_max_tokens_per_append:
            handle = self._cache_result(
                session_id=session_id,
                tool_name=tool_name,
                args=args,
                items=items,
                raw_payload=raw_payload,
                options=options,
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
            options=options,
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
            options=handle.mediation,
            source_details=f"Paginated Canvas MCP result_id={handle.result_id} page={page}/{page_count} from {handle.tool_name}.",
        )

        header = (
            f"result_id={handle.result_id}; tool={handle.tool_name}; page={page}/{page_count}; "
            f"total_items={total_items}; page_size={page_size}\n"
        )
        return ToolDispatchResult(
            output_text=header + rendered.output_text,
            sources=rendered.sources,
        )

    async def _render_payload(
        self,
        *,
        tool_name: str,
        payload: Any,
        user_question: str,
        budget_plan: ContextBudgetPlan,
        current_prompt_tokens: int,
        summarize_func: SummarizeFunc | None,
        options: _MediationOptions,
        source_details: str,
    ) -> ToolDispatchResult:
        mediated_payload, provenance = self._mediate_payload(payload, options=options)
        serialized = self._serialize_payload(mediated_payload)
        estimated_tokens = estimate_tokens_from_text(serialized)
        available_tokens = budget_plan.available_tool_tokens(current_prompt_tokens)

        if available_tokens <= 0:
            return ToolDispatchResult(
                output_text=(
                    "Canvas tool result withheld due to context budget limits (0 tokens available for tool payload). "
                    "Use pagination helpers to request a smaller subset."
                ),
                sources=[
                    {
                        "source_type": "canvas_tool",
                        "source_id": tool_name,
                        "label": f"Canvas tool {tool_name}",
                        "details": source_details,
                    }
                ],
            )

        if estimated_tokens > available_tokens:
            if options.mediation_mode == "full":
                return ToolDispatchResult(
                    output_text=(
                        "Canvas tool payload exceeds context budget in full mode. "
                        "Use pagination helpers or switch to mediation_mode='full_if_fits'."
                    ),
                    sources=[
                        {
                            "source_type": "canvas_tool",
                            "source_id": tool_name,
                            "label": f"Canvas tool {tool_name}",
                            "details": source_details,
                        }
                    ],
                )
            if summarize_func is not None:
                try:
                    summarized = await summarize_func(
                        (
                            "Summarize this Canvas tool payload for the user question while preserving actionable IDs, "
                            "exact due dates, numeric values, and assignment/rubric requirements. "
                            f"Question: {user_question}"
                        ),
                        serialized,
                        max_output_tokens=min(available_tokens, self._settings.openai_summarizer_max_output_tokens),
                    )
                    serialized = summarized
                    estimated_tokens = estimate_tokens_from_text(serialized)
                except Exception as exc:
                    logger.warning("Summarizer fallback not available for tool=%s error=%s", tool_name, exc)

        if estimated_tokens > available_tokens:
            return ToolDispatchResult(
                output_text=(
                    "Canvas tool payload remains too large for current context budget. "
                    "Request a narrower page/filter or use canvas_get_result_page with smaller page_size."
                ),
                sources=[
                    {
                        "source_type": "canvas_tool",
                        "source_id": tool_name,
                        "label": f"Canvas tool {tool_name}",
                        "details": source_details,
                    }
                ],
            )

        wrapper = {
            "tool": tool_name,
            "items": mediated_payload if isinstance(mediated_payload, list) else [mediated_payload],
            "provenance": provenance,
        }
        output_text = self._serialize_payload(wrapper)
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
        options: _MediationOptions,
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
            mediation=options,
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

    def _default_mediation_for_direct_call(self, tool_name: str) -> _MediationOptions:
        if tool_name in {"canvas_get_assignment", "get_assignment"}:
            return _MediationOptions(
                fields=None,
                mediation_mode="full_if_fits",
                include_description=True,
                include_rubric=True,
                include_attachments=True,
                include_submission=True,
            )
        return _MediationOptions(
            fields=None,
            mediation_mode="compact",
            include_description=False,
            include_rubric=False,
            include_attachments=False,
            include_submission=False,
        )

    def _should_force_paginate(self, tool_name: str, args: dict[str, Any]) -> bool:
        if tool_name in HIGH_VOLUME_TOOLS:
            if bool(args.get("include_submissions", False)):
                return True
            if tool_name in {"canvas_list_files", "list_files"}:
                return True
        return False

    def _estimated_payload_tokens(self, payload: Any) -> int:
        return estimate_tokens_from_text(self._serialize_payload(payload))

    def _serialize_payload(self, payload: Any) -> str:
        try:
            return json.dumps(payload, ensure_ascii=True, default=str)
        except TypeError:
            return str(payload)

    def _mediate_payload(self, payload: Any, *, options: _MediationOptions) -> tuple[Any, dict[str, list[str]]]:
        fields_present: list[str] = []
        fields_missing_from_source: list[str] = []
        fields_omitted_by_budget: list[str] = []

        desired = list(options.fields or [])
        if options.include_description and "description" not in desired:
            desired.append("description")
        if options.include_rubric and "rubric" not in desired:
            desired.append("rubric")
        if options.include_attachments and "attachments" not in desired:
            desired.append("attachments")
        if options.include_submission and "submission" not in desired:
            desired.append("submission")

        if options.mediation_mode == "full":
            projected = payload
        elif options.mediation_mode == "full_if_fits":
            projected = payload
        else:
            projected = self._project_payload(payload, desired)

        source_keys = self._collect_top_level_keys(payload)
        projected_keys = self._collect_top_level_keys(projected)
        for field in desired:
            if field in source_keys:
                fields_present.append(field)
                if field not in projected_keys:
                    fields_omitted_by_budget.append(field)
            else:
                fields_missing_from_source.append(field)

        provenance = {
            "fields_present": sorted(set(fields_present)),
            "fields_missing_from_source": sorted(set(fields_missing_from_source)),
            "fields_omitted_by_budget": sorted(set(fields_omitted_by_budget)),
        }
        return projected, provenance

    def _collect_top_level_keys(self, payload: Any) -> set[str]:
        if isinstance(payload, dict):
            keys = set(payload.keys())
            if "items" in payload and isinstance(payload["items"], list) and payload["items"]:
                first = payload["items"][0]
                if isinstance(first, dict):
                    keys |= set(first.keys())
            return keys
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            return set(payload[0].keys())
        return set()

    def _project_payload(self, payload: Any, desired_fields: list[str]) -> Any:
        default_fields = [
            "id",
            "name",
            "title",
            "course_id",
            "assignment_id",
            "due_at",
            "points_possible",
            "submission_types",
            "score",
            "workflow_state",
            "html_url",
        ]
        fields = list(dict.fromkeys(default_fields + desired_fields))

        def project_item(item: Any) -> Any:
            if not isinstance(item, dict):
                return item
            out: dict[str, Any] = {}
            for field in fields:
                if field in item:
                    out[field] = item[field]
            return out

        if isinstance(payload, list):
            return [project_item(item) for item in payload]
        if isinstance(payload, dict):
            copied: dict[str, Any] = {}
            if "items" in payload and isinstance(payload["items"], list):
                copied.update({k: v for k, v in payload.items() if k != "items"})
                copied["items"] = [project_item(item) for item in payload["items"]]
                return copied
            if "assignments" in payload and isinstance(payload["assignments"], list):
                copied.update({k: v for k, v in payload.items() if k != "assignments"})
                copied["assignments"] = [project_item(item) for item in payload["assignments"]]
                return copied
            return project_item(payload)
        return payload

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
                "description": "Run a Canvas MCP tool with wrapper args for mediation and field retention.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "tool_name": {"type": "string"},
                        "args": {"type": "object", "additionalProperties": True},
                        "fields": {"type": "array", "items": {"type": "string"}},
                        "mediation_mode": {"type": "string", "enum": ["compact", "full_if_fits", "full"]},
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
