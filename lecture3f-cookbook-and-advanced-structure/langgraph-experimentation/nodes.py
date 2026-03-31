from __future__ import annotations

import os
from typing import Any

from state import Approval, Intent, StudyState
from tools import fetch_mock_context
from tools import format_bullets


def _append_event(state: StudyState, event: str) -> list[str]:
    existing = state.get("events", [])
    return [*existing, event]


def classify_intent(state: StudyState) -> dict[str, Any]:
    text = state.get("user_input", "").lower()
    intent: Intent
    if any(token in text for token in ("quiz", "question", "practice test")):
        intent = "quiz"
    elif any(token in text for token in ("plan", "schedule", "study")):
        intent = "plan"
    else:
        intent = "clarify"
    return {
        "intent": intent,
        "events": _append_event(state, f"classify_intent:{intent}"),
    }


def fetch_context(state: StudyState) -> dict[str, Any]:
    intent = state.get("intent", "clarify")
    user_input = state.get("user_input", "")
    context_items = fetch_mock_context(intent, user_input)
    return {
        "context_items": context_items,
        "events": _append_event(state, f"fetch_context:{len(context_items)}"),
    }


def _mock_draft(state: StudyState) -> str:
    intent = state.get("intent", "clarify")
    context_items = state.get("context_items", [])
    review_note = state.get("review_note", "").strip()
    prefix = {
        "plan": "Study Plan Draft",
        "quiz": "Quiz Draft",
        "clarify": "Clarification Draft",
    }.get(intent, "Draft")

    sections: list[str] = [f"## {prefix}", format_bullets(context_items)]
    if review_note:
        sections.append(f"Reviewer note addressed: {review_note}")
    return "\n\n".join(part for part in sections if part.strip())


def _openai_draft(state: StudyState) -> str:
    from langchain_openai import ChatOpenAI

    model_name = os.getenv("OPENAI_MODEL", "gpt-5-nano")
    llm = ChatOpenAI(model=model_name, temperature=0)
    prompt = (
        "You are generating a concise study assistant output.\n"
        f"Intent: {state.get('intent', 'clarify')}\n"
        f"User input: {state.get('user_input', '')}\n"
        "Context items:\n"
        f"{format_bullets(state.get('context_items', []))}\n"
        f"Review note: {state.get('review_note', '')}\n"
        "Return a practical markdown response."
    )
    response = llm.invoke(prompt)
    return str(response.content)


def draft_response(state: StudyState) -> dict[str, Any]:
    use_mock = os.getenv("USE_MOCK_LLM", "true").lower() == "true"
    api_key_present = bool(os.getenv("OPENAI_API_KEY"))

    if use_mock or not api_key_present:
        draft = _mock_draft(state)
        mode = "mock"
    else:
        draft = _openai_draft(state)
        mode = "openai"

    return {
        "draft": draft,
        "events": _append_event(state, f"draft_response:{mode}"),
    }


def human_review(state: StudyState) -> dict[str, Any]:
    approval: Approval = state.get("approval", "approved")
    revision_count = int(state.get("revision_count", 0))

    if approval == "needs_edits" and revision_count >= 1:
        # Auto-approve after one revision to keep demo runs bounded.
        approval = "approved"

    updates: dict[str, Any] = {
        "approval": approval,
        "events": _append_event(state, f"human_review:{approval}"),
    }
    if approval == "needs_edits":
        updates["revision_count"] = revision_count + 1
    return updates


def finalize_response(state: StudyState) -> dict[str, Any]:
    draft = state.get("draft", "")
    final_response = draft or "I need more information to respond."
    history = [*state.get("history", []), final_response]
    return {
        "final_response": final_response,
        "history": history,
        "events": _append_event(state, "finalize_response"),
    }


def route_by_intent(state: StudyState) -> str:
    return state.get("intent", "clarify")


def route_by_review(state: StudyState) -> str:
    if state.get("approval") == "needs_edits":
        return "revise"
    return "approved"
