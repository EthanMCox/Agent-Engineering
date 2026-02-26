import csv
import json
import logging
import os
import re
import time
from collections import Counter
from statistics import median
from typing import Any

from fastapi import FastAPI
from fastmcp import FastMCP

DATA_FILE = os.path.join(os.path.dirname(__file__), "agent_engineer_opinions.csv")

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have",
    "he", "i", "in", "is", "it", "its", "my", "not", "of", "on", "or", "our", "that",
    "the", "their", "them", "they", "this", "to", "was", "we", "with", "you", "your",
    "but", "so", "if", "do", "does", "can", "just", "very", "too", "more", "one",
}

POSITIVE_TERMS = {
    "great", "love", "best", "glorious", "useful", "nice", "heavenly", "must", "life", "warm",
    "perfect", "amazing", "good", "euphoric", "resource", "helpful",
}

NEGATIVE_TERMS = {
    "bad", "hate", "disgusting", "mistake", "dangerous", "scary", "nah", "questionable", "slander",
    "damaging", "horrid", "over", "hyped",
}


def _is_number(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False


class DataStore:
    def __init__(self, path: str):
        self.path = path
        self.rows: list[dict[str, str]] = []
        self.headers: list[str] = []
        self.numeric_columns: list[str] = []
        self.text_columns: list[str] = []
        self._load()

    def _load(self) -> None:
        with open(self.path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            self.rows = list(reader)
            self.headers = reader.fieldnames or []

        numeric_cols = []
        text_cols = []
        for col in self.headers:
            if col in {"Timestamp", "Expert Name"}:
                continue
            values = [r.get(col, "").strip() for r in self.rows if r.get(col, "").strip()]
            if values and all(_is_number(v) for v in values):
                numeric_cols.append(col)
            else:
                text_cols.append(col)

        self.numeric_columns = numeric_cols
        self.text_columns = text_cols


store = DataStore(DATA_FILE)
mcp = FastMCP(name="agent-engineer-opinions")


def _build_mcp_http_app() -> Any:
    # Prefer stateless mode for connector compatibility; fall back if unavailable.
    try:
        return mcp.http_app(path="/", stateless_http=True)
    except TypeError:
        return mcp.http_app(path="/")


mcp_app = _build_mcp_http_app()
logger = logging.getLogger("mcp_access")
logger.setLevel(logging.INFO)


def _safe_json(value: Any, max_len: int = 1200) -> str:
    """Serialize structured values for logs without unbounded size."""
    try:
        text = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(value)
    if len(text) > max_len:
        return f"{text[:max_len]}...<truncated>"
    return text


class MCPAcceptCompat:
    """Normalizes Accept headers for clients that omit text/event-stream."""

    def __init__(self, wrapped_app: Any):
        self.wrapped_app = wrapped_app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") == "http":
            headers = list(scope.get("headers", []))
            accept_idx = None
            accept_val = b""

            for idx, (key, value) in enumerate(headers):
                if key.lower() == b"accept":
                    accept_idx = idx
                    accept_val = value.lower()
                    break

            desired = b"application/json, text/event-stream"
            if accept_idx is None:
                headers.append((b"accept", desired))
            elif b"application/json" in accept_val and b"text/event-stream" not in accept_val:
                headers[accept_idx] = (b"accept", headers[accept_idx][1] + b", text/event-stream")

            scope = dict(scope)
            scope["headers"] = headers

        await self.wrapped_app(scope, receive, send)


class MCPRequestLogger:
    """Logs incoming MCP requests and responses for CloudWatch visibility."""

    def __init__(self, wrapped_app: Any):
        self.wrapped_app = wrapped_app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.wrapped_app(scope, receive, send)
            return

        method = scope.get("method", "")
        path = scope.get("path", "")
        client = scope.get("client")
        client_ip = client[0] if client else "-"

        # Buffer request body once, then replay it to the wrapped app unchanged.
        buffered_messages: list[dict[str, Any]] = []
        body_parts: list[bytes] = []
        while True:
            message = await receive()
            buffered_messages.append(message)
            if message.get("type") != "http.request":
                break
            body_parts.append(message.get("body", b""))
            if not message.get("more_body", False):
                break

        body = b"".join(body_parts)
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        content_type = headers.get(b"content-type", b"").decode("latin-1")

        rpc_method = None
        rpc_id = None
        tool_name = None
        tool_args: Any = None
        if method == "POST" and "application/json" in content_type and body:
            try:
                payload = json.loads(body.decode("utf-8"))
                if isinstance(payload, dict):
                    rpc_method = payload.get("method")
                    rpc_id = payload.get("id")
                    if rpc_method == "tools/call":
                        params = payload.get("params", {})
                        if isinstance(params, dict):
                            tool_name = params.get("name")
                            tool_args = params.get("arguments")
            except (UnicodeDecodeError, json.JSONDecodeError):
                rpc_method = "invalid-json"

        logger.info(
            "mcp_request method=%s path=%s client=%s rpc_method=%s tool=%s id=%s args=%s",
            method,
            path,
            client_ip,
            rpc_method,
            tool_name,
            rpc_id,
            _safe_json(tool_args),
        )

        buffered_iter = iter(buffered_messages)

        async def replay_receive() -> dict[str, Any]:
            try:
                return next(buffered_iter)
            except StopIteration:
                # After replaying buffered request frames, defer to the real
                # receive channel so disconnect timing is preserved.
                return await receive()

        status_code: int | None = None

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = message.get("status")
            await send(message)

        started = time.perf_counter()
        try:
            await self.wrapped_app(scope, replay_receive, send_wrapper)
        finally:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.info(
                "mcp_response method=%s path=%s status=%s duration_ms=%s rpc_method=%s tool=%s id=%s args=%s",
                method,
                path,
                status_code,
                elapsed_ms,
                rpc_method,
                tool_name,
                rpc_id,
                _safe_json(tool_args),
            )


@mcp.tool
def data_catalog() -> dict[str, Any]:
    """Return dataset metadata and available subjects."""
    return {
        "dataset": "agent_engineer_opinions.csv",
        "total_responses": len(store.rows),
        "headers": store.headers,
        "numeric_subjects": store.numeric_columns,
        "text_subjects": store.text_columns,
        "responder_names": [r.get("Expert Name", "") for r in store.rows],
    }


@mcp.tool
def sample_opinions(subject: str, limit: int = 7) -> dict[str, Any]:
    """Return up to `limit` sample responses for a single subject."""
    if not subject:
        raise ValueError("'subject' is required.")
    if subject not in store.headers:
        raise ValueError(f"Unknown subject '{subject}'.")
    safe_limit = max(1, min(limit, 25))

    sample: list[dict[str, Any]] = []
    for row in store.rows[:safe_limit]:
        item: dict[str, Any] = {
            "expert_name": row.get("Expert Name", ""),
            "timestamp": row.get("Timestamp", ""),
        }
        item["subject"] = subject
        item["opinion"] = row.get(subject, "")
        sample.append(item)

    return {"count": len(sample), "sample": sample}


def _top_terms(texts: list[str], top_n: int = 8) -> list[tuple[str, int]]:
    counts: Counter[str] = Counter()
    for text in texts:
        for token in re.findall(r"[a-zA-Z']+", text.lower()):
            if token in STOPWORDS or len(token) < 3:
                continue
            counts[token] += 1
    return counts.most_common(top_n)


def _sentiment_bucket(text: str) -> str:
    terms = {t for t in re.findall(r"[a-zA-Z']+", text.lower())}
    pos = len(terms & POSITIVE_TERMS)
    neg = len(terms & NEGATIVE_TERMS)
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"


def _subject_stats(subject: str) -> dict[str, Any]:
    """Internal implementation for summary statistics."""
    if subject not in store.headers:
        raise ValueError(f"Unknown subject '{subject}'.")

    entries = [
        {
            "expert_name": r.get("Expert Name", ""),
            "value": r.get(subject, "").strip(),
        }
        for r in store.rows
        if r.get(subject, "").strip()
    ]
    values = [e["value"] for e in entries]

    if subject in store.numeric_columns:
        nums = [float(v) for v in values]
        dist = Counter(int(n) if n.is_integer() else n for n in nums)
        return {
            "subject": subject,
            "type": "numeric",
            "response_count": len(nums),
            "mean": round(sum(nums) / len(nums), 3),
            "median": median(nums),
            "min": min(nums),
            "max": max(nums),
            "distribution": dict(sorted(dist.items(), key=lambda kv: kv[0])),
            "responses_by_expert": [
                {"expert_name": e["expert_name"], "rating": float(e["value"])}
                for e in entries
            ],
        }

    sentiments = Counter(_sentiment_bucket(v) for v in values)
    return {
        "subject": subject,
        "type": "text",
        "response_count": len(values),
        "avg_comment_length": round(sum(len(v) for v in values) / len(values), 2),
        "top_terms": _top_terms(values),
        "sentiment_summary": dict(sentiments),
        "sample_comments": [
            {"expert_name": e["expert_name"], "comment": e["value"]}
            for e in entries[:3]
        ],
    }


@mcp.tool
def subject_stats(subject: str) -> dict[str, Any]:
    """Return summary statistics for one subject."""
    return _subject_stats(subject)


@mcp.tool
def summarize_subject(subject: str) -> str:
    """Return a concise plain-language summary of how responders feel about one subject."""
    stats = _subject_stats(subject)
    if stats["type"] == "numeric":
        return (
            f"{subject}: average rating {stats['mean']} out of 5 "
            f"(min {stats['min']}, max {stats['max']}, n={stats['response_count']})."
        )

    sentiments = stats["sentiment_summary"]
    top_terms = ", ".join(t for t, _ in stats["top_terms"][:5])
    return (
        f"{subject}: {stats['response_count']} comments, average length {stats['avg_comment_length']} chars. "
        f"Sentiment mix {sentiments}. Frequent themes: {top_terms}."
    )

###################################################################################
########################## Define the FastAPI Interface ###########################
###################################################################################


app = FastAPI(
    title="Agent Engineer Opinions MCP",
    version="0.2.0",
    lifespan=mcp_app.lifespan,
)
app.mount("/mcp", MCPRequestLogger(MCPAcceptCompat(mcp_app)))


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "service": "agent-engineer-opinions-fastmcp",
        "mcp_endpoint": "/mcp",
        "health_endpoint": "/health",
        "tool_hint": "Use MCP tools data_catalog, sample_opinions, subject_stats, summarize_subject",
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "responses_loaded": len(store.rows)}
