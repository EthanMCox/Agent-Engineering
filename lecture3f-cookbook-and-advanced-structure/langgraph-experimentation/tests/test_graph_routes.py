from __future__ import annotations

from nodes import classify_intent
from nodes import route_by_intent
from nodes import route_by_review


def test_intent_routing_plan() -> None:
    state = {"user_input": "Can you make me a study plan?"}
    updates = classify_intent(state)
    assert updates["intent"] == "plan"
    assert route_by_intent(updates) == "plan"


def test_intent_routing_quiz() -> None:
    state = {"user_input": "Give me a short quiz."}
    updates = classify_intent(state)
    assert updates["intent"] == "quiz"
    assert route_by_intent(updates) == "quiz"


def test_review_routes() -> None:
    assert route_by_review({"approval": "approved"}) == "approved"
    assert route_by_review({"approval": "needs_edits"}) == "revise"
