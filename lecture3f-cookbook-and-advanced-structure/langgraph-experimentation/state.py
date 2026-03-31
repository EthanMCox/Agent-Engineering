from __future__ import annotations

from typing import Literal, TypedDict


Intent = Literal["plan", "quiz", "clarify"]
Approval = Literal["approved", "needs_edits"]


class StudyState(TypedDict, total=False):
    thread_id: str
    user_input: str
    intent: Intent
    context_items: list[str]
    draft: str
    approval: Approval
    review_note: str
    revision_count: int
    final_response: str
    history: list[str]
    events: list[str]
