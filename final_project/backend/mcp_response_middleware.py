from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, TypedDict

from .context_budget import ContextBudgetPlan, estimate_tokens_from_text
from .settings import AppSettings
from .temporal_context import current_local_date

logger = logging.getLogger("canvas_study_coach.backend.mcp_response_middleware")

SummarizeFunc = Callable[[str, str, int], Awaitable[str]]

DEFAULT_RETAIN_FIELDS = [
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

CONTAINER_LIST_KEYS = ("items", "assignments", "courses", "files", "modules", "rubrics", "data", "results")
TEMPORAL_FIELDS = [
    "due_at",
    "start_at",
    "end_at",
    "unlock_at",
    "lock_at",
    "created_at",
    "updated_at",
    "term",
    "enrollment_term_id",
    "term_id",
]


class ChunkSummary(TypedDict):
    key_facts: list[str]
    ids: list[str]
    dates: list[str]
    numeric_values: list[str]
    constraints: list[str]
    missing_data: list[str]


class MCPResponseEnvelope(TypedDict, total=False):
    version: str
    tool: str
    status: str
    policy_path: str
    token_estimate_before: int
    token_estimate_after: int
    available_tool_tokens: int
    fields_present: list[str]
    fields_retained: list[str]
    fields_dropped: list[str]
    payload: Any
    summary: ChunkSummary | None
    pagination: dict[str, Any] | None
    warnings: list[str]
    provenance: dict[str, Any]


@dataclass(slots=True)
class MiddlewareResult:
    envelope_dict: MCPResponseEnvelope
    serialized_output: str
    token_metrics: dict[str, int]
    processing_flags: dict[str, bool]


class MCPResponseMiddleware:
    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings

    async def process(
        self,
        *,
        tool_name: str,
        raw_payload: Any,
        user_question: str,
        budget_plan: ContextBudgetPlan,
        current_prompt_tokens: int,
        summarize_func: SummarizeFunc | None,
        pagination: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> MiddlewareResult:
        payload = self._sanitize_json_value(raw_payload)
        available_tokens = budget_plan.available_tool_tokens(current_prompt_tokens)

        top_level_fields, item_fields, item_count = self._inspect_payload(payload)
        fields_present = sorted(set(top_level_fields + item_fields))

        serialized_before = self._serialize_json(payload)
        token_before = estimate_tokens_from_text(serialized_before)

        logger.info(
            "MCP middleware initial payload tool=%s token_before=%d available_tool_tokens=%d current_prompt_tokens=%d fields_present=%d item_count=%d",
            tool_name,
            token_before,
            available_tokens,
            current_prompt_tokens,
            len(fields_present),
            item_count,
        )

        warnings: list[str] = []
        processing_flags = {
            "middleware_enabled": bool(self._settings.mcp_response_middleware_enabled),
            "llm_field_selector_used": False,
            "llm_chunk_summarizer_used": False,
            "llm_merge_used": False,
            "deterministic_fallback_used": False,
            "budget_pressure": available_tokens <= 0,
            "chunking_used": False,
        }

        if not self._settings.mcp_response_middleware_enabled:
            warnings.append("MCP response middleware is disabled; returning safe pass-through envelope.")
            envelope = self._build_envelope(
                tool_name=tool_name,
                status="ok",
                policy_path="pass_through",
                token_before=token_before,
                available_tokens=available_tokens,
                fields_present=fields_present,
                fields_retained=fields_present,
                fields_dropped=[],
                payload=payload,
                summary=None,
                pagination=pagination,
                warnings=warnings,
                provenance=provenance or {},
            )
            return self._finalize(envelope, token_before, processing_flags)

        should_compress = token_before > self._settings.mcp_response_pass_through_max_tokens or token_before > available_tokens
        if not should_compress:
            envelope = self._build_envelope(
                tool_name=tool_name,
                status="ok",
                policy_path="pass_through",
                token_before=token_before,
                available_tokens=available_tokens,
                fields_present=fields_present,
                fields_retained=fields_present,
                fields_dropped=[],
                payload=payload,
                summary=None,
                pagination=pagination,
                warnings=warnings,
                provenance=provenance or {},
            )
            return self._finalize(envelope, token_before, processing_flags)

        retain_fields = self._default_retain_fields(fields_present, user_question)
        if summarize_func is not None and item_fields:
            try:
                selected = await self._select_fields_with_llm(
                    summarize_func=summarize_func,
                    tool_name=tool_name,
                    user_question=user_question,
                    top_level_fields=top_level_fields,
                    item_fields=item_fields,
                )
                if selected:
                    retain_fields = selected
                    processing_flags["llm_field_selector_used"] = True
            except Exception as exc:
                warnings.append(f"Field selector unavailable; using deterministic fields ({type(exc).__name__}).")
                logger.warning("MCP field selector fallback tool=%s error=%s", tool_name, exc)

        projected_payload = self._project_payload(payload, retain_fields)
        serialized_projected = self._serialize_json(projected_payload)
        token_after_projection = estimate_tokens_from_text(serialized_projected)
        fields_retained = sorted(set(self._collect_present_fields(projected_payload)) & set(fields_present))
        fields_dropped = sorted(set(fields_present) - set(fields_retained))

        if token_after_projection <= available_tokens:
            envelope = self._build_envelope(
                tool_name=tool_name,
                status="ok",
                policy_path="projected",
                token_before=token_before,
                available_tokens=available_tokens,
                fields_present=fields_present,
                fields_retained=fields_retained,
                fields_dropped=fields_dropped,
                payload=projected_payload,
                summary=None,
                pagination=pagination,
                warnings=warnings,
                provenance=provenance or {},
            )
            return self._finalize(envelope, token_after_projection, processing_flags)

        if summarize_func is not None:
            try:
                chunk_summaries = await self._summarize_projected_payload_in_chunks(
                    summarize_func=summarize_func,
                    tool_name=tool_name,
                    user_question=user_question,
                    projected_payload=projected_payload,
                    processing_flags=processing_flags,
                )
                merged_summary = await self._hierarchically_merge_summaries(
                    summarize_func=summarize_func,
                    tool_name=tool_name,
                    user_question=user_question,
                    summaries=chunk_summaries,
                    processing_flags=processing_flags,
                )
                compact_summary = self._compact_summary(merged_summary)
                summary_tokens = estimate_tokens_from_text(self._serialize_json(compact_summary))
                if summary_tokens <= max(available_tokens, 1):
                    envelope = self._build_envelope(
                        tool_name=tool_name,
                        status="ok",
                        policy_path="chunk_summarized",
                        token_before=token_before,
                        available_tokens=available_tokens,
                        fields_present=fields_present,
                        fields_retained=fields_retained,
                        fields_dropped=fields_dropped,
                        payload=None,
                        summary=compact_summary,
                        pagination=pagination,
                        warnings=warnings,
                        provenance=provenance or {},
                    )
                    return self._finalize(envelope, summary_tokens, processing_flags)
                warnings.append("Chunk summary still exceeded context budget; deterministic fallback applied.")
            except Exception as exc:
                warnings.append(f"LLM summarization path failed; deterministic fallback applied ({type(exc).__name__}).")
                logger.warning("MCP response summarization fallback tool=%s error=%s", tool_name, exc)

        processing_flags["deterministic_fallback_used"] = True
        deterministic_payload = self._deterministic_compact(projected_payload)
        token_after_deterministic = estimate_tokens_from_text(self._serialize_json(deterministic_payload))

        if token_after_deterministic > max(available_tokens, 1):
            deterministic_payload = {"preview": self._deterministic_preview(projected_payload), "item_count": item_count}
            token_after_deterministic = estimate_tokens_from_text(self._serialize_json(deterministic_payload))
            warnings.append("Payload was aggressively compacted due to strict context budget.")

        envelope = self._build_envelope(
            tool_name=tool_name,
            status="degraded",
            policy_path="deterministic_fallback",
            token_before=token_before,
            available_tokens=available_tokens,
            fields_present=fields_present,
            fields_retained=fields_retained,
            fields_dropped=fields_dropped,
            payload=deterministic_payload,
            summary=None,
            pagination=pagination,
            warnings=warnings,
            provenance=provenance or {},
        )
        return self._finalize(envelope, token_after_deterministic, processing_flags)

    def _finalize(
        self,
        envelope: MCPResponseEnvelope,
        token_after: int,
        processing_flags: dict[str, bool],
    ) -> MiddlewareResult:
        envelope["token_estimate_after"] = max(1, token_after)
        safe_envelope = self._sanitize_json_value(envelope)
        serialized_output = self._serialize_json(safe_envelope)
        token_metrics = {
            "token_estimate_before": int(safe_envelope.get("token_estimate_before", 0)),
            "token_estimate_after": int(safe_envelope.get("token_estimate_after", estimate_tokens_from_text(serialized_output))),
            "available_tool_tokens": int(safe_envelope.get("available_tool_tokens", 0)),
        }
        return MiddlewareResult(
            envelope_dict=safe_envelope,
            serialized_output=serialized_output,
            token_metrics=token_metrics,
            processing_flags=processing_flags,
        )

    def _build_envelope(
        self,
        *,
        tool_name: str,
        status: str,
        policy_path: str,
        token_before: int,
        available_tokens: int,
        fields_present: list[str],
        fields_retained: list[str],
        fields_dropped: list[str],
        payload: Any,
        summary: ChunkSummary | None,
        pagination: dict[str, Any] | None,
        warnings: list[str],
        provenance: dict[str, Any],
    ) -> MCPResponseEnvelope:
        return {
            "version": "mcp_response_envelope.v1",
            "tool": tool_name,
            "status": status,
            "policy_path": policy_path,
            "token_estimate_before": max(1, token_before),
            "available_tool_tokens": max(0, available_tokens),
            "fields_present": sorted(set(fields_present)),
            "fields_retained": sorted(set(fields_retained)),
            "fields_dropped": sorted(set(fields_dropped)),
            "payload": payload,
            "summary": summary,
            "pagination": pagination,
            "warnings": warnings[:8],
            "provenance": provenance,
        }

    async def _select_fields_with_llm(
        self,
        *,
        summarize_func: SummarizeFunc,
        tool_name: str,
        user_question: str,
        top_level_fields: list[str],
        item_fields: list[str],
    ) -> list[str]:
        question_preview = user_question.strip().replace("\n", " ")
        if len(question_preview) > 180:
            question_preview = f"{question_preview[:180]}..."

        logger.info(
            "MCP field selector start tool=%s candidate_top_level=%d candidate_item=%d question=%r",
            tool_name,
            len(top_level_fields),
            len(item_fields),
            question_preview,
        )

        content = {
            "tool_name": tool_name,
            "user_question": user_question,
            "reference_date": current_local_date().isoformat(),
            "top_level_fields": top_level_fields[:100],
            "item_fields": item_fields[:200],
            "max_fields": self._settings.mcp_response_field_selector_max_fields,
        }
        instruction = (
            "Select the minimum field names needed to answer the user question from this MCP tool payload. "
            "Return JSON only with exactly this shape: {\"retain_fields\": [\"field_name\"]}. "
            "Do not include fields not present in candidates. "
            "If the question implies time context (semester/term/current/upcoming/today/week/month), prioritize temporal fields "
            "such as due_at/start_at/end_at/term/enrollment_term_id when available."
        )
        raw = await self._call_small_model(
            summarize_func=summarize_func,
            instruction=instruction,
            content=self._serialize_json(content),
            max_output_tokens=min(350, self._settings.openai_summarizer_max_output_tokens),
        )
        parsed = json.loads(raw)
        raw_fields = parsed.get("retain_fields", [])
        if not isinstance(raw_fields, list):
            return []
        candidates = set(top_level_fields + item_fields)
        selected: list[str] = []
        for item in raw_fields:
            value = str(item).strip()
            if not value or value not in candidates:
                continue
            if value in selected:
                continue
            selected.append(value)
            if len(selected) >= self._settings.mcp_response_field_selector_max_fields:
                break

        logger.info(
            "MCP field selector decision tool=%s selected_count=%d selected_fields=%s",
            tool_name,
            len(selected),
            selected,
        )
        return selected

    async def _summarize_projected_payload_in_chunks(
        self,
        *,
        summarize_func: SummarizeFunc,
        tool_name: str,
        user_question: str,
        projected_payload: Any,
        processing_flags: dict[str, bool],
    ) -> list[ChunkSummary]:
        chunks = self._payload_chunks(projected_payload)
        processing_flags["chunking_used"] = len(chunks) > 1
        summaries: list[ChunkSummary] = []
        for idx, chunk in enumerate(chunks, start=1):
            content = {
                "tool_name": tool_name,
                "user_question": user_question,
                "reference_date": current_local_date().isoformat(),
                "chunk_index": idx,
                "chunk_count": len(chunks),
                "chunk_payload": chunk,
            }
            instruction = (
                "Summarize this MCP payload chunk while preserving critical identifiers, dates, numeric values, "
                "constraints, and missing-data notes. Return JSON only with exactly these keys: "
                "{\"key_facts\":[],\"ids\":[],\"dates\":[],\"numeric_values\":[],\"constraints\":[],\"missing_data\":[]}."
            )
            raw = await self._call_small_model(
                summarize_func=summarize_func,
                instruction=instruction,
                content=self._serialize_json(content),
                max_output_tokens=min(500, self._settings.openai_summarizer_max_output_tokens),
            )
            processing_flags["llm_chunk_summarizer_used"] = True
            summaries.append(self._normalize_chunk_summary(json.loads(raw)))
        return summaries

    async def _hierarchically_merge_summaries(
        self,
        *,
        summarize_func: SummarizeFunc,
        tool_name: str,
        user_question: str,
        summaries: list[ChunkSummary],
        processing_flags: dict[str, bool],
    ) -> ChunkSummary:
        if not summaries:
            return self._empty_chunk_summary()

        current = [self._normalize_chunk_summary(item) for item in summaries]
        fanin = max(2, self._settings.mcp_response_hierarchical_merge_fanin)
        while len(current) > 1:
            merged_round: list[ChunkSummary] = []
            for start in range(0, len(current), fanin):
                group = current[start : start + fanin]
                if len(group) == 1:
                    merged_round.append(group[0])
                    continue
                content = {
                    "tool_name": tool_name,
                    "user_question": user_question,
                    "reference_date": current_local_date().isoformat(),
                    "child_summaries": group,
                }
                instruction = (
                    "Merge child summaries without introducing new facts. Return JSON only with exactly these keys: "
                    "{\"key_facts\":[],\"ids\":[],\"dates\":[],\"numeric_values\":[],\"constraints\":[],\"missing_data\":[]}."
                )
                raw = await self._call_small_model(
                    summarize_func=summarize_func,
                    instruction=instruction,
                    content=self._serialize_json(content),
                    max_output_tokens=min(450, self._settings.openai_summarizer_max_output_tokens),
                )
                processing_flags["llm_merge_used"] = True
                merged_round.append(self._normalize_chunk_summary(json.loads(raw)))
            current = merged_round
        return current[0]

    def _payload_chunks(self, payload: Any) -> list[Any]:
        chunk_target = max(200, self._settings.mcp_response_chunk_target_tokens)
        max_chunks = max(1, self._settings.mcp_response_max_chunks)

        container_key, items = self._extract_items(payload)
        if not items:
            return [payload]

        chunks: list[list[Any]] = []
        active: list[Any] = []
        active_tokens = 0
        for item in items:
            item_tokens = estimate_tokens_from_text(self._serialize_json(item))
            if active and active_tokens + item_tokens > chunk_target:
                chunks.append(active)
                active = [item]
                active_tokens = item_tokens
            else:
                active.append(item)
                active_tokens += item_tokens
        if active:
            chunks.append(active)

        if len(chunks) > max_chunks:
            overflow = [item for group in chunks[max_chunks - 1 :] for item in group]
            chunks = chunks[: max_chunks - 1] + [overflow]

        if container_key is None:
            return [chunk for chunk in chunks]

        base: dict[str, Any] = {}
        if isinstance(payload, dict):
            base = {k: v for k, v in payload.items() if k != container_key}
        out: list[Any] = []
        for chunk in chunks:
            wrapped = dict(base)
            wrapped[container_key] = chunk
            out.append(wrapped)
        return out

    def _extract_items(self, payload: Any) -> tuple[str | None, list[Any]]:
        if isinstance(payload, list):
            return None, payload
        if isinstance(payload, dict):
            for key in CONTAINER_LIST_KEYS:
                value = payload.get(key)
                if isinstance(value, list):
                    return key, value
        return None, []

    def _project_payload(self, payload: Any, retain_fields: list[str]) -> Any:
        fields = list(dict.fromkeys(DEFAULT_RETAIN_FIELDS + retain_fields))

        def project_item(item: Any) -> Any:
            if not isinstance(item, dict):
                return item
            out: dict[str, Any] = {}
            for field in fields:
                if field in item:
                    out[field] = item[field]
            if not out:
                for fallback in ("id", "name", "title"):
                    if fallback in item:
                        out[fallback] = item[fallback]
            return out

        if isinstance(payload, list):
            return [project_item(item) for item in payload]
        if isinstance(payload, dict):
            copied: dict[str, Any] = {}
            key, items = self._extract_items(payload)
            if key is not None:
                copied.update({k: v for k, v in payload.items() if k != key})
                copied[key] = [project_item(item) for item in items]
                return copied
            return project_item(payload)
        return payload

    def _deterministic_compact(self, payload: Any) -> Any:
        key, items = self._extract_items(payload)
        if not items:
            return payload
        head = items[:5]
        tail = items[-2:] if len(items) > 7 else []
        compact_items = head + tail
        if key is None:
            return compact_items
        out = {k: v for k, v in payload.items() if k != key} if isinstance(payload, dict) else {}
        out[key] = compact_items
        out["omitted_item_count"] = max(0, len(items) - len(compact_items))
        return out

    def _deterministic_preview(self, payload: Any) -> Any:
        if isinstance(payload, dict):
            preview: dict[str, Any] = {}
            for key in list(payload.keys())[:6]:
                preview[key] = payload[key]
            return preview
        if isinstance(payload, list):
            return payload[:3]
        return payload

    def _default_retain_fields(self, fields_present: list[str], user_question: str) -> list[str]:
        selected = [field for field in DEFAULT_RETAIN_FIELDS if field in fields_present]
        question = user_question.lower()
        if self._is_temporal_query(question):
            for field in TEMPORAL_FIELDS:
                if field in fields_present and field not in selected:
                    selected.append(field)
        if "rubric" in question and "rubric" in fields_present:
            selected.append("rubric")
        if "description" in question and "description" in fields_present:
            selected.append("description")
        if "submission" in question and "submission" in fields_present:
            selected.append("submission")
        return list(dict.fromkeys(selected))[: self._settings.mcp_response_field_selector_max_fields]

    def _is_temporal_query(self, question: str) -> bool:
        return any(
            token in question
            for token in (
                "semester",
                "term",
                "current",
                "upcoming",
                "this week",
                "next week",
                "today",
                "tomorrow",
                "month",
                "deadline",
                "due",
            )
        )

    def _inspect_payload(self, payload: Any) -> tuple[list[str], list[str], int]:
        top_level: set[str] = set()
        item_fields: set[str] = set()
        item_count = 0

        if isinstance(payload, dict):
            top_level.update(str(key) for key in payload.keys())
            _, items = self._extract_items(payload)
            item_count = len(items)
            for item in items[:30]:
                if isinstance(item, dict):
                    item_fields.update(str(key) for key in item.keys())
            if not items:
                item_fields.update(str(key) for key in payload.keys())
        elif isinstance(payload, list):
            item_count = len(payload)
            for item in payload[:30]:
                if isinstance(item, dict):
                    item_fields.update(str(key) for key in item.keys())
        return sorted(top_level), sorted(item_fields), item_count

    def _collect_present_fields(self, payload: Any) -> list[str]:
        top_level, item_fields, _ = self._inspect_payload(payload)
        return sorted(set(top_level + item_fields))

    async def _call_small_model(
        self,
        *,
        summarize_func: SummarizeFunc,
        instruction: str,
        content: str,
        max_output_tokens: int,
    ) -> str:
        timeout = max(1.0, float(self._settings.mcp_response_llm_timeout_seconds))
        output = await asyncio.wait_for(
            summarize_func(instruction, content, max_output_tokens=max_output_tokens),
            timeout=timeout,
        )
        text = output.strip()
        if not text:
            raise RuntimeError("Summarizer returned empty content.")
        return text

    def _normalize_chunk_summary(self, payload: Any) -> ChunkSummary:
        if not isinstance(payload, dict):
            return self._empty_chunk_summary()
        out = self._empty_chunk_summary()
        for key in out.keys():
            value = payload.get(key, [])
            if not isinstance(value, list):
                continue
            cleaned: list[str] = []
            for item in value:
                text = str(item).strip()
                if not text:
                    continue
                cleaned.append(text[:240])
                if len(cleaned) >= 16:
                    break
            out[key] = cleaned
        return out

    def _compact_summary(self, summary: ChunkSummary) -> ChunkSummary:
        compact = self._empty_chunk_summary()
        for key, value in summary.items():
            compact[key] = [str(item)[:200] for item in value[:10]]
        return compact

    def _empty_chunk_summary(self) -> ChunkSummary:
        return {
            "key_facts": [],
            "ids": [],
            "dates": [],
            "numeric_values": [],
            "constraints": [],
            "missing_data": [],
        }

    def _sanitize_json_value(self, value: Any, depth: int = 0) -> Any:
        if depth > 8:
            return str(value)[:800]
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return value[:4000]
        if isinstance(value, list):
            return [self._sanitize_json_value(item, depth + 1) for item in value[:200]]
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for idx, (key, item) in enumerate(value.items()):
                if idx >= 120:
                    break
                safe_key = str(key)[:120]
                out[safe_key] = self._sanitize_json_value(item, depth + 1)
            return out
        return str(value)[:800]

    def _serialize_json(self, payload: Any) -> str:
        return json.dumps(payload, ensure_ascii=True, default=str)
