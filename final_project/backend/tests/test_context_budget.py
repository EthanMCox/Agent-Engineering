from __future__ import annotations

from backend.context_budget import ContextBudgetPlan
from backend.context_budget import estimate_tokens_from_messages
from backend.context_budget import estimate_tokens_from_text


def test_estimate_tokens_from_text_and_messages() -> None:
    text_tokens = estimate_tokens_from_text("abcd" * 50)
    assert text_tokens > 0
    msg_tokens = estimate_tokens_from_messages(
        [
            {"role": "system", "content": "hello"},
            {"role": "user", "content": "world"},
        ]
    )
    assert msg_tokens > 0


def test_context_budget_plan_limits_tool_tokens() -> None:
    plan = ContextBudgetPlan(
        max_input_tokens=10000,
        reserved_output_tokens=2000,
        reserved_system_tokens=1000,
        max_tool_tokens_per_append=1200,
    )
    assert plan.max_prompt_tokens == 7000
    assert plan.available_tool_tokens(current_prompt_tokens=6500) == 500
    assert plan.available_tool_tokens(current_prompt_tokens=2000) == 1200

