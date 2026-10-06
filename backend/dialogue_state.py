"""Session-owned, bounded working memory; no LLM or external-source lookup."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from . import conversation_state, db, request_context

log = logging.getLogger(__name__)
PENDING_TTL_SECONDS = 600
FOCUS_TTL_SECONDS = 86400
MAX_FOCUS = 8
ROLES = {"last_created", "last_updated", "last_completed", "last_selected", "parent", "child", "mentioned"}


def _fresh(timestamp: Any, seconds: int) -> bool:
    try:
        value = datetime.fromisoformat(str(timestamp))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - value).total_seconds()
        return 0 <= age <= seconds
    except (TypeError, ValueError):
        return False


def entity(task: dict[str, Any], role: str, *, turn_id: str | None = None) -> dict[str, Any] | None:
    task_id = task.get("entity_id", task.get("id"))
    if isinstance(task_id, bool) or not str(task_id or "").isdigit() or int(task_id) < 1:
        return None
    title = str(task.get("title") or "").strip()
    if not title:
        return None
    return {"entity_type": "task", "entity_id": int(task_id), "title": title[:180],
            "source": str(task.get("source") or "local"), "role": role,
            "turn_id": turn_id or uuid4().hex, "updated_at": db.now_iso()}


def load(session_id: str | None) -> dict[str, Any]:
    if not session_id:
        return {}
    try:
        state = conversation_state.load(session_id) or {}
        if not state:
            return {}
        state["focus_stack"] = [item for item in state.get("focus_stack", [])
                                if isinstance(item, dict) and item.get("entity_type") == "task"
                                and item.get("role") in ROLES and entity(item, item["role"])
                                and _fresh(item.get("updated_at"), FOCUS_TTL_SECONDS)][-MAX_FOCUS:]
        pending = state.get("pending_dialogue")
        if (not isinstance(pending, dict) or not _fresh(pending.get("created_at"), PENDING_TTL_SECONDS)
                or pending.get("owner") != "tasks" or not pending.get("id")
                or not isinstance(pending.get("operation"), dict)
                or pending["operation"].get("kind") not in {"create_child_task", "update_task", "complete_task", "select_task"}
                or not isinstance(pending.get("candidates"), list)
                or any(not isinstance(item, dict) or item.get("entity_type") != "task"
                       or not entity(item, "mentioned") for item in pending.get("candidates", []))):
            state["pending_dialogue"] = None
        return state
    except Exception:
        log.exception("dialogue state unavailable session_id=%s", session_id)
        return {}


def _mutate(session_id: str | None, change) -> bool:
    if not session_id:
        return False
    try:
        conversation_state.ensure_schema()
        with db.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT OR IGNORE INTO conversation_state (session_id, updated_at) VALUES (?, ?)",
                         (session_id, db.now_iso()))
            row = conn.execute("SELECT focus_stack, last_action, pending_dialogue FROM conversation_state WHERE session_id=?",
                               (session_id,)).fetchone()
            state = {}
            for key in row.keys():
                try:
                    state[key] = json.loads(row[key])
                except (ValueError, TypeError):
                    state[key] = [] if key == "focus_stack" else None
            if not change(state):
                return False
            conn.execute("UPDATE conversation_state SET focus_stack=?, last_action=?, pending_dialogue=?, updated_at=? WHERE session_id=?",
                         (*(json.dumps(state[key], ensure_ascii=False) for key in ("focus_stack", "last_action", "pending_dialogue")),
                          db.now_iso(), session_id))
        return True
    except Exception:
        log.exception("dialogue state update failed session_id=%s", session_id)
        return False


def remember(session_id: str | None, items: list[dict[str, Any]], action: dict[str, Any] | None = None) -> bool:
    def change(state):
        stack = state.get("focus_stack") if isinstance(state.get("focus_stack"), list) else []
        for item in items:
            stack = [old for old in stack if isinstance(old, dict) and old.get("entity_id") != item["entity_id"]]
            stack.append(item)
        state["focus_stack"] = stack[-MAX_FOCUS:]
        if action:
            state["last_action"] = action
        return True
    return _mutate(session_id, change)


def set_pending(session_id: str | None, operation: dict[str, Any], candidates: list[dict[str, Any]], original_request: str) -> bool:
    pending = {"id": uuid4().hex, "owner": "tasks", "kind": operation["kind"],
               "original_request": original_request[:500], "operation": operation,
               "missing_slot": "parent_task" if operation["kind"] == "create_child_task" else "task",
               "candidates": candidates[:MAX_FOCUS], "created_at": db.now_iso()}
    def change(state):
        state["pending_dialogue"] = pending
        return True
    return _mutate(session_id, change)


def take_pending(session_id: str | None, pending_id: str) -> bool:
    """Consume exactly once, before writes; concurrent/replayed replies cannot repeat them."""
    def change(state):
        pending = state.get("pending_dialogue")
        if not isinstance(pending, dict) or pending.get("id") != pending_id:
            return False
        state["pending_dialogue"] = None
        return True
    return _mutate(session_id, change)


def observe_tool_result(*, session_id: str | None, tool: str, arguments: dict[str, Any], result: Any) -> None:
    success_key = {"create_task": "created", "update_task": "updated", "complete_task": "completed", "set_task_parent": "updated"}.get(tool)
    if not session_id or not success_key:
        return
    try:
        data = json.loads(result) if isinstance(result, str) else result
        if not isinstance(data, dict) or data.get(success_key) is not True or data.get("error") or data.get("partial_update"):
            return
        task = data.get("task")
        if not isinstance(task, dict):
            return
        turn_id = request_context.current_ids()[0] or uuid4().hex
        role = {"create_task": "last_created", "update_task": "last_updated", "complete_task": "last_completed", "set_task_parent": "child"}[tool]
        item = entity(task, role, turn_id=turn_id)
        if not item:
            return
        items = []
        if tool == "set_task_parent" and task.get("parent_task_id"):
            from . import task_hierarchy
            parent = task_hierarchy._find_task(task["parent_task_id"])
            related = entity(parent, "parent", turn_id=turn_id) if parent else None
            if related:
                items.append(related)
        items.append(item)
        remember(session_id, items, {"tool": tool, "entity_type": "task", "entity_id": item["entity_id"],
                                     "turn_id": turn_id, "updated_at": db.now_iso()})
    except Exception:
        log.exception("tool dialogue observation failed tool=%s", tool)
