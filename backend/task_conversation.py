"""Deterministic conversational bridge from task activity to a create proposal."""
from __future__ import annotations

import json
import re
from typing import Any

from . import tools

_TASK_ACTIVITY_PATTERN = re.compile(
    r"^(?:今[、,\s]*)?(?P<title>.+?)(?:っていう|って言う|という|って)"
    r"タスク(?:を)?(?:やってる|やっている|進めてる|進めている|してる|している)"
    r"(?:んだ|よ|ところ)?[。.!！]*$"
)


def _normalize_title(value: str) -> str:
    return re.sub(r"[\s　、。,.!！?？『』「」\"'・]", "", str(value or "")).casefold()


def _task_title_from_activity(message: str) -> str | None:
    match = _TASK_ACTIVITY_PATTERN.match(str(message or "").strip())
    if not match:
        return None
    title = match.group("title").strip(" 　、。,.!！?？『』「」\"'")
    if not title or len(title) > 120:
        return None
    return title


def try_handle_task_activity(message: str) -> dict[str, Any] | None:
    """Offer one safe create action when a stated active task is not registered."""
    title = _task_title_from_activity(message)
    if title is None:
        return None

    args = {"status": "all", "limit": 100}
    content = tools.dispatch("get_tasks", args)
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or data.get("error"):
        return None

    target = _normalize_title(title)
    existing = next(
        (
            task
            for task in data.get("tasks") or []
            if isinstance(task, dict) and _normalize_title(task.get("title")) == target
        ),
        None,
    )
    used_tools = [{"name": "get_tasks", "arguments": json.dumps(args, ensure_ascii=False)}]
    model_route = {
        "kind": "task_activity",
        "requested_route": "deterministic",
        "actual_route": "deterministic",
        "model": None,
        "base_url_id": None,
        "tools": ["get_tasks"],
        "reasons": ["deterministic_task_activity"],
    }
    if existing is not None:
        return {
            "reply": f"そうなんだ。『{title}』はタスクに登録済みだよ。",
            "used_tools": used_tools,
            "persist": True,
            "model_route": model_route,
        }

    create_args = {"title": title, "priority": "High"}
    return {
        "reply": f"そうなんだ。『{title}』っていうタスクはまだないから、追加する？",
        "used_tools": used_tools,
        "pending_actions": [{"name": "create_task", "arguments": create_args}],
        "persist": True,
        "model_route": model_route | {"tools": ["get_tasks", "create_task"]},
    }
