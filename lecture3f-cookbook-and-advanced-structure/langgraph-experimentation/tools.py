from __future__ import annotations

from collections.abc import Iterable


MOCK_PLAN_ITEMS: list[str] = [
    "Review lecture notes for 25 minutes",
    "Work 3 practice problems from the last assignment",
    "Summarize key formulas on one page",
]

MOCK_QUIZ_ITEMS: list[str] = [
    "Question 1: Explain the main concept in your own words.",
    "Question 2: Solve a short application problem.",
    "Question 3: Identify one common mistake and correct it.",
]


def fetch_mock_context(intent: str, user_input: str) -> list[str]:
    lowered = user_input.lower()
    if intent == "quiz":
        return MOCK_QUIZ_ITEMS.copy()
    if intent == "plan":
        items = MOCK_PLAN_ITEMS.copy()
        if "calculus" in lowered:
            items.append("Focus on derivatives and chain rule review")
        if "exam" in lowered:
            items.append("Reserve a final 20-minute mixed review block")
        return items
    return ["Please clarify your goal (study plan vs quiz practice)."]


def format_bullets(items: Iterable[str]) -> str:
    return "\n".join(f"- {item}" for item in items)
