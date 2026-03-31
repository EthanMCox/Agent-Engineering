from __future__ import annotations

from app import inspect_thread
from app import invoke_graph


def test_state_persistence_with_same_thread_id() -> None:
    thread_id = "pytest-thread-demo"

    first = invoke_graph(
        thread_id=thread_id,
        message="Help me study calculus",
        approval="approved",
    )
    assert first.get("final_response")

    second = invoke_graph(
        thread_id=thread_id,
        message="Now make me a short quiz",
        approval="approved",
    )
    assert second.get("final_response")

    summary = inspect_thread(thread_id)
    assert summary["thread_id"] == thread_id
    assert isinstance(summary["history_count"], int)
    assert summary["history_count"] >= 1
