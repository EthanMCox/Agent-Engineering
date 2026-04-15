from __future__ import annotations

import argparse
import asyncio
import json
import time
from typing import Any

from .context_budget import ContextBudgetPlan
from .mcp_client import CanvasMCPClient
from .settings import load_settings
from .tool_registry import CanvasToolRegistry


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe Canvas MCP tools without running chat flow.")
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="List available MCP tools and exit.",
    )
    parser.add_argument(
        "--tool",
        default="",
        help="Tool name to call (for example: canvas_list_courses).",
    )
    parser.add_argument(
        "--args",
        default="{}",
        help="JSON object arguments for the tool call.",
    )
    return parser.parse_args()


def _format_exception(exc: Exception) -> str:
    detail = str(exc).strip()
    if detail:
        return f"{type(exc).__name__}: {detail}"
    return type(exc).__name__


def _parse_json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"--args must be valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("--args must be a JSON object.")
    return parsed


async def _run(args: argparse.Namespace) -> int:
    settings = load_settings()
    client = CanvasMCPClient(settings=settings)
    registry = CanvasToolRegistry(client, settings=settings)

    if not settings.canvas_mcp_enabled:
        print("ERROR: CANVAS_MCP_ENABLED is false. Enable it in .env or environment variables.")
        return 2

    try:
        await client.start()

        if args.list_tools:
            start = time.perf_counter()
            definitions = await client.list_tool_definitions()
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            names = sorted(tool.get("name", "") for tool in definitions if tool.get("name"))
            print(json.dumps({"ok": True, "count": len(names), "elapsed_ms": elapsed_ms, "tools": names}, indent=2))
            return 0

        if not args.tool:
            print("ERROR: Provide --list-tools or --tool <name>.")
            return 2

        payload = _parse_json_object(args.args)
        start = time.perf_counter()
        result = await registry.dispatch_tool_call(
            args.tool,
            payload,
            session_id="probe",
            user_question="probe",
            budget_plan=ContextBudgetPlan(
                max_input_tokens=settings.context_max_input_tokens,
                reserved_output_tokens=settings.context_reserved_output_tokens,
                reserved_system_tokens=settings.context_reserved_system_tokens,
                max_tool_tokens_per_append=settings.tool_result_max_tokens_per_append,
            ),
            current_prompt_tokens=0,
            summarize_func=None,
        )
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        print(
            json.dumps(
                {
                    "ok": True,
                    "tool": args.tool,
                    "elapsed_ms": elapsed_ms,
                    "output_chars": len(result.output_text),
                    "sources": result.sources,
                    "output": result.output_text,
                },
                indent=2,
            )
        )
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": _format_exception(exc),
                },
                indent=2,
            )
        )
        return 1
    finally:
        await client.stop()


def main() -> int:
    args = _parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
