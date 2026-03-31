from __future__ import annotations

import argparse
import json
import os
from typing import Any

from app import inspect_thread
from app import invoke_graph
from app import stream_graph
from app import get_thread_values
from state import Approval


def _normalize_approval(value: str | None) -> Approval:
    if value and value.lower() in {"no", "n", "needs_edits", "edit"}:
        return "needs_edits"
    return "approved"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LangGraph Study Flow demo CLI")
    parser.add_argument("--thread-id", required=True, help="Thread identifier for checkpointed runs.")
    parser.add_argument("--message", default="", help="User request for the graph.")
    parser.add_argument("--approve", default="yes", help="yes/no approval used by human review node.")
    parser.add_argument("--review-note", default="", help="Optional edit note for the review loop.")
    parser.add_argument("--inspect", action="store_true", help="Inspect latest checkpoint summary and exit.")
    parser.add_argument("--no-stream", action="store_true", help="Disable streaming node updates.")
    return parser


def _print_stream_chunk(chunk: dict[str, Any]) -> None:
    for node_name, updates in chunk.items():
        if isinstance(updates, dict):
            keys = ", ".join(sorted(updates.keys()))
            print(f"[node:{node_name}] updated keys: {keys}")
        else:
            print(f"[node:{node_name}] {updates}")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    approval = _normalize_approval(args.approve)

    if args.inspect:
        summary = inspect_thread(args.thread_id)
        print(json.dumps(summary, indent=2))
        return 0

    if not args.message.strip():
        parser.error("--message is required unless --inspect is used.")

    os.environ.setdefault("USE_MOCK_LLM", "true")

    if not args.no_stream:
        print("Streaming graph updates:")
        for chunk in stream_graph(
            thread_id=args.thread_id,
            message=args.message,
            approval=approval,
            review_note=args.review_note,
        ):
            _print_stream_chunk(chunk)
        result = get_thread_values(args.thread_id)
    else:
        result = invoke_graph(
            thread_id=args.thread_id,
            message=args.message,
            approval=approval,
            review_note=args.review_note,
        )
    print("\nFinal response:\n")
    print(result.get("final_response", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
