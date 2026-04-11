from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


def estimate_tokens_from_text(text: str) -> int:
    # Safe approximation without tokenizer dependency.
    if not text:
        return 0
    return max(1, len(text) // 4)


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        try:
            return json.dumps(value, ensure_ascii=True, default=str)
        except TypeError:
            return str(value)
    if isinstance(value, list):
        return "\n".join(_to_text(item) for item in value)
    return str(value)


def estimate_tokens_from_messages(messages: list[Any]) -> int:
    total = 0
    for message in messages:
        total += estimate_tokens_from_text(_to_text(message))
    return total


@dataclass(slots=True)
class ContextBudgetPlan:
    max_input_tokens: int
    reserved_output_tokens: int
    reserved_system_tokens: int
    max_tool_tokens_per_append: int

    @property
    def max_prompt_tokens(self) -> int:
        return max(
            512,
            self.max_input_tokens - self.reserved_output_tokens - self.reserved_system_tokens,
        )

    def remaining_prompt_tokens(self, current_prompt_tokens: int) -> int:
        return max(0, self.max_prompt_tokens - current_prompt_tokens)

    def available_tool_tokens(self, current_prompt_tokens: int) -> int:
        return min(
            self.max_tool_tokens_per_append,
            self.remaining_prompt_tokens(current_prompt_tokens),
        )

