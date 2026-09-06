"""Compact per-session conversation state for PETIT.

The state is intentionally small and deterministic. It complements, rather than
replaces, conversation history and long-term memory. Updating it must not add an
extra LLM call to ordinary chat turns.
"""
from __future__ import annotations

import json
import re
from typing import Any

from . import config, db, project_continuity

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversation_state (
    session_id TEXT PRIMARY KEY,
    current_topic TEXT,
    user_goal TEXT,
    recent_decisions TEXT NOT NULL DEFAULT '[]',
    unresolved_items TEXT NOT NULL DEFAULT '[]',
    active_project TEXT,
    active_task TEXT,
    recent_entities TEXT NOT NULL DEFAULT '[]',
    last_user_text TEXT,
    last_assistant_text TEXT,
    confidence REAL NOT NULL DEFAULT 1.0,
    updated_at TEXT NOT NULL
);
"""

_MAX_TOPIC = 180
_MAX_GOAL = 220
_MAX_LAST_TEXT = 360
_MAX_LIST_ITEMS = 5
_MAX_ITEM = 180
_CONTINUATION = re.compile(r"^(?:あれ|それ|これ|さっき|続き|その続き|例の|うん|そう|で、|じゃあ|ちなみに)")
_DECISION = re.compile(r"(?:にする|でいく|採用|決め|導入|やることに|方針で|進めることに)")
_UNRESOLVED = re.compile(r"(?:未確認|確認が必要|不明|分から|できなかった|失敗|未解決|要確認)")
_ENTITY = re.compile(r"[「『\"`]([^」』\"`]{2,80})[」』\"`]|\b([A-Za-z][A-Za-z0-9_.#/-]{2,40})\b")


def ensure_schema() -> None:
    with db.get_connection() as conn:
        conn.executescript(_SCHEMA)


def _load_json_list(value: str | None) -> list[str]:
    try:
        data = json.loads(value or "[]")
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    result: list[str] = []
    for item in data:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text[:_MAX_ITEM])
    return result[:_MAX_LIST_ITEMS]


def _append_unique(items: list[str], value: str | None) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return items[:_MAX_LIST_ITEMS]
    text = text[:_MAX_ITEM]
    result = [item for item in items if item != text]
    result.append(text)
    return result[-_MAX_LIST_ITEMS:]


def load(session_id: str | None) -> dict[str, Any] | None:
    session_id = str(session_id or "").strip()
    if not session_id:
        return None
    ensure_schema()
    with db.get_connection() as conn:
        row = conn.execute("SELECT * FROM conversation_state WHERE session_id=?", (session_id,)).fetchone()
    if not row:
        return None
    result = dict(row)
    result["recent_decisions"] = _load_json_list(result.get("recent_decisions"))
    result["unresolved_items"] = _load_json_list(result.get("unresolved_items"))
    result["recent_entities"] = _load_json_list(result.get("recent_entities"))
    try:
        result["active_project"] = json.loads(result["active_project"]) if result.get("active_project") else None
    except json.JSONDecodeError:
        result["active_project"] = None
    return result


def _extract_entities(text: str) -> list[str]:
    result: list[str] = []
    for match in _ENTITY.finditer(text or ""):
        value = next((group for group in match.groups() if group), "").strip()
        if value and value.casefold() not in {"https", "http"} and value not in result:
            result.append(value[:80])
        if len(result) >= _MAX_LIST_ITEMS:
            break
    return result


def _active_project() -> dict[str, Any] | None:
    try:
        project = project_continuity.get_active_project(config.PETIT_OWNER_ID)
    except Exception:  # best effort only; state must never break chat
        return None
    if not project:
        return None
    return {
        "id": project.get("project_id"),
        "name": project.get("name"),
        "status": project.get("status"),
    }


def update_after_turn(
    session_id: str | None,
    *,
    user_text: str,
    assistant_text: str,
    active_task: str | None = None,
) -> dict[str, Any] | None:
    """Update compact state without invoking an LLM."""
    session_id = str(session_id or "").strip()
    if not session_id:
        return None
    ensure_schema()
    previous = load(session_id) or {}
    user_text = " ".join(str(user_text or "").split())
    assistant_text = " ".join(str(assistant_text or "").split())
    continuation = bool(_CONTINUATION.search(user_text))

    current_topic = previous.get("current_topic") if continuation and previous.get("current_topic") else user_text[:_MAX_TOPIC]
    user_goal = previous.get("user_goal") if continuation and previous.get("user_goal") else user_text[:_MAX_GOAL]

    decisions = list(previous.get("recent_decisions") or [])
    if _DECISION.search(user_text):
        decisions = _append_unique(decisions, user_text)

    unresolved = list(previous.get("unresolved_items") or [])
    if _UNRESOLVED.search(assistant_text):
        unresolved = _append_unique(unresolved, assistant_text)
    elif unresolved and not _UNRESOLVED.search(assistant_text):
        # Keep history compact: resolved turns gradually evict old uncertainty.
        unresolved = unresolved[-(_MAX_LIST_ITEMS - 1):]

    entities = list(previous.get("recent_entities") or [])
    for entity in _extract_entities(user_text):
        entities = _append_unique(entities, entity)

    project = _active_project()
    now = db.now_iso()
    project_json = json.dumps(project, ensure_ascii=False) if project else None
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO conversation_state (session_id, current_topic, user_goal, recent_decisions, unresolved_items, "
            "active_project, active_task, recent_entities, last_user_text, last_assistant_text, confidence, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1.0, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET current_topic=excluded.current_topic, user_goal=excluded.user_goal, "
            "recent_decisions=excluded.recent_decisions, unresolved_items=excluded.unresolved_items, active_project=excluded.active_project, "
            "active_task=excluded.active_task, recent_entities=excluded.recent_entities, last_user_text=excluded.last_user_text, "
            "last_assistant_text=excluded.last_assistant_text, confidence=excluded.confidence, updated_at=excluded.updated_at",
            (
                session_id,
                current_topic,
                user_goal,
                json.dumps(decisions, ensure_ascii=False),
                json.dumps(unresolved, ensure_ascii=False),
                project_json,
                str(active_task or previous.get("active_task") or "").strip()[:_MAX_ITEM] or None,
                json.dumps(entities, ensure_ascii=False),
                user_text[:_MAX_LAST_TEXT],
                assistant_text[:_MAX_LAST_TEXT],
                now,
            ),
        )
    return load(session_id)


def render_for_model(state: dict[str, Any] | None, *, max_chars: int = 1600) -> str:
    if not state:
        return ""
    lines = ["[Conversation State]"]
    if state.get("current_topic"):
        lines.append(f"current_topic: {state['current_topic']}")
    if state.get("user_goal"):
        lines.append(f"user_goal: {state['user_goal']}")
    project = state.get("active_project") or {}
    if project:
        lines.append(f"active_project: {project.get('name') or project.get('id')}")
    if state.get("active_task"):
        lines.append(f"active_task: {state['active_task']}")
    if state.get("recent_decisions"):
        lines.append("recent_decisions: " + " | ".join(state["recent_decisions"][-3:]))
    if state.get("unresolved_items"):
        lines.append("unresolved_items: " + " | ".join(state["unresolved_items"][-3:]))
    if state.get("recent_entities"):
        lines.append("recent_entities: " + ", ".join(state["recent_entities"][-5:]))
    if state.get("last_user_text"):
        lines.append(f"last_user: {state['last_user_text']}")
    rendered = "\n".join(lines)
    return rendered[:max(200, int(max_chars))]
