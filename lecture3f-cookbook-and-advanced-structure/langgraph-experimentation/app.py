from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from checkpointer import create_sqlite_checkpointer
from graph import build_graph
from state import Approval, StudyState


load_dotenv(override=True)

CHECKPOINT_DB_PATH = os.getenv("CHECKPOINT_DB_PATH", "./data/checkpoints.sqlite")

_checkpointer = create_sqlite_checkpointer(CHECKPOINT_DB_PATH)
_compiled_graph = build_graph().compile(checkpointer=_checkpointer)


def invoke_graph(
    *,
    thread_id: str,
    message: str,
    approval: Approval = "approved",
    review_note: str = "",
) -> StudyState:
    input_state: StudyState = {
        "thread_id": thread_id,
        "user_input": message,
        "approval": approval,
        "review_note": review_note,
        "revision_count": 0,
    }
    config = {"configurable": {"thread_id": thread_id}}
    result = _compiled_graph.invoke(input_state, config=config)
    return result


def stream_graph(
    *,
    thread_id: str,
    message: str,
    approval: Approval = "approved",
    review_note: str = "",
) -> Iterator[dict[str, Any]]:
    input_state: StudyState = {
        "thread_id": thread_id,
        "user_input": message,
        "approval": approval,
        "review_note": review_note,
        "revision_count": 0,
    }
    config = {"configurable": {"thread_id": thread_id}}
    for chunk in _compiled_graph.stream(input_state, config=config, stream_mode="updates"):
        yield chunk


def inspect_thread(thread_id: str) -> dict[str, Any]:
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = _compiled_graph.get_state(config)
    values = snapshot.values if snapshot and getattr(snapshot, "values", None) else {}
    return {
        "thread_id": thread_id,
        "checkpoint_db_path": str(Path(CHECKPOINT_DB_PATH).resolve()),
        "last_intent": values.get("intent"),
        "last_event": (values.get("events") or [None])[-1],
        "history_count": len(values.get("history", [])),
    }


def get_thread_values(thread_id: str) -> StudyState:
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = _compiled_graph.get_state(config)
    values = snapshot.values if snapshot and getattr(snapshot, "values", None) else {}
    return values
