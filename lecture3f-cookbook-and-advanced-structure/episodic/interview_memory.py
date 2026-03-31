import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

MEMORY_PATH = Path(__file__).with_name("interview_memory.json")


def _load_store() -> dict:
    if not MEMORY_PATH.exists():
        return {"sessions": []}
    return json.loads(MEMORY_PATH.read_text())


def _save_store(store: dict) -> None:
    MEMORY_PATH.write_text(json.dumps(store, indent=2))


def list_sessions() -> dict:
    """
    Return a list of sessions with basic metadata and stored summaries.
    """
    store = _load_store()
    sessions = store.get("sessions", [])
    out = []
    for s in sessions:
        out.append({
            "session_id": s.get("session_id"),
            "timestamp": s.get("timestamp"),
            "topic": s.get("topic"),
            "mode": s.get("mode"),
            "linked_session_ids": s.get("linked_session_ids", []),
            "summary": s.get("summary", "")
        })
    return {"sessions": out}


def get_session(session_id: str) -> dict:
    """
    Return the full session data for a given session_id.
    """
    store = _load_store()
    for s in store.get("sessions", []):
        if s.get("session_id") == session_id:
            return {"session": s}
    return {"session": None}


def save_session(
        session_id: str | None,
        topic: str,
        mode: str,
        transcript: str,
        evaluation: str,
        summary: str,
        linked_session_ids: str | None = None
) -> dict:
    """
    Save a session and return its session_id.
    """
    store = _load_store()
    if not session_id:
        session_id = str(uuid.uuid4())
    if linked_session_ids:
        linked_session_ids = json.loads(linked_session_ids)
    else:
        linked_session_ids = []
    if transcript:
        transcript = json.loads(transcript)
    else:
        transcript = []
    payload = {
        "session_id": session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "topic": topic,
        "mode": mode,
        "linked_session_ids": linked_session_ids,
        "transcript": transcript,
        "evaluation": evaluation,
        "summary": summary
    }
    # replace if exists
    sessions = store.get("sessions", [])
    for i, s in enumerate(sessions):
        if s.get("session_id") == session_id:
            sessions[i] = payload
            break
    else:
        sessions.append(payload)
    store["sessions"] = sessions
    _save_store(store)
    return {"session_id": session_id}


def link_sessions(session_id: str, linked_session_ids: str) -> dict:
    """
    Add linked session ids to a session.
    """
    store = _load_store()
    sessions = store.get("sessions", [])
    for s in sessions:
        if s.get("session_id") == session_id:
            existing = set(s.get("linked_session_ids", []))
            new_links = json.loads(linked_session_ids) if linked_session_ids else []
            existing.update(new_links)
            s["linked_session_ids"] = sorted(existing)
            _save_store(store)
            return {"session_id": session_id, "linked_session_ids": s["linked_session_ids"]}
    return {"session_id": session_id, "linked_session_ids": []}


def summarize_sessions() -> dict:
    """
    Return a short summary list for planning.
    """
    store = _load_store()
    sessions = store.get("sessions", [])
    out = []
    for s in sessions:
        out.append({
            "session_id": s.get("session_id"),
            "timestamp": s.get("timestamp"),
            "topic": s.get("topic"),
            "mode": s.get("mode"),
            "summary": s.get("summary", ""),
            "linked_session_ids": s.get("linked_session_ids", [])
        })
    return {"sessions": out}
