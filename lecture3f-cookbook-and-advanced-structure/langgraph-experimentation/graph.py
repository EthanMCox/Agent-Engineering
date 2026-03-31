from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from nodes import classify_intent
from nodes import draft_response
from nodes import fetch_context
from nodes import finalize_response
from nodes import human_review
from nodes import route_by_intent
from nodes import route_by_review
from state import StudyState


def build_graph():
    workflow = StateGraph(StudyState)
    workflow.add_node("classify_intent", classify_intent)
    workflow.add_node("fetch_context", fetch_context)
    workflow.add_node("draft_response", draft_response)
    workflow.add_node("human_review", human_review)
    workflow.add_node("finalize_response", finalize_response)

    workflow.add_edge(START, "classify_intent")
    workflow.add_conditional_edges(
        "classify_intent",
        route_by_intent,
        {
            "plan": "fetch_context",
            "quiz": "fetch_context",
            "clarify": "fetch_context",
        },
    )
    workflow.add_edge("fetch_context", "draft_response")
    workflow.add_edge("draft_response", "human_review")
    workflow.add_conditional_edges(
        "human_review",
        route_by_review,
        {
            "revise": "draft_response",
            "approved": "finalize_response",
        },
    )
    workflow.add_edge("finalize_response", END)
    return workflow
