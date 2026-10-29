"""Resolve named task resumption before the project-continuity fast path."""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from . import config, project_router, tools
from .tools.work_sessions import resolve_task

_RESUME = re.compile(
    r"^(?P<target>.+?)(?:を|は)?\s*再開(?:する|して(?:ください|ほしい)?|します)?[。.!！]*$"
)
_PREFIX = re.compile(r"^(?:じゃあ|では|今から|これから|次は)\s*")


def _response(reply: str, reason: str, used_tools: list[dict[str, Any]] | None = None,
              *, persist: bool = True) -> dict[str, Any]:
    return {
        "reply": reply,
        "used_tools": used_tools or [],
        "persist": persist,
        "model_route": {
            "kind": "direct", "requested_route": "deterministic", "actual_route": "deterministic",
            "model": None, "llm_call_count": 0, "reasons": [f"named_task_resume:{reason}"],
        },
    }


def try_handle(message: str) -> dict[str, Any] | None:
    text = unicodedata.normalize("NFKC", message).strip()
    match = _RESUME.fullmatch(text)
    if not match:
        return None
    target = _PREFIX.sub("", match["target"]).strip().strip("「」『』\"'")
    # Project intent stays with Project Continuity even when a Task shares its name.
    if re.search(r"プロジェクト|\bproject\b", target, re.IGNORECASE):
        return None
    stripped = re.sub(r"(?:の)?(?:タスク|作業)$", "", target).strip().strip("「」『』\"'")
    explicit_task = stripped != target
    if explicit_task and not stripped:
        return _response("再開するタスク名を指定してください。", "missing_target")
    queries = list(dict.fromkeys(query for query in (target, stripped) if query))
    resolved: dict[str, Any] = {}
    # A literal title wins; then absorb the user's Task/Work suffix. Only after
    # those exact matches fail do we consider unique partial matches.
    for allow_partial in (False, True):
        for query in queries:
            resolved = resolve_task(task=query, allow_partial=allow_partial)
            if resolved.get("task") or resolved.get("candidates"):
                break
        else:
            continue
        break

    if not resolved.get("task") and not resolved.get("candidates"):
        if not explicit_task:
            return None
        return _response(f"「{stripped or target}」に一致する未完了タスクが見つかりません。タスク名を確認してください。",
                         "no_candidate")

    if not explicit_task:
        project = project_router.resolve_project(text, user_id=config.PETIT_OWNER_ID)
        if project.kind in {"resolved", "ambiguous"}:
            return _response(
                f"「{target}」はタスクとプロジェクトの両方に一致します。"
                f"「{target}タスク再開」か「{target}プロジェクト再開」で指定してください。",
                "task_project_collision",
            )

    candidates = resolved.get("candidates")
    if candidates:
        labels = "、".join(f"「{item['task']}」" for item in candidates)
        return _response(f"候補が複数あります。タスク名を指定して再開するか、Tasks画面で対象を選んで開始してください。{labels}",
                         "multiple_candidates")

    selected = resolved["task"]
    arguments = {"task_id": selected["task_id"]}
    raw = tools.dispatch("start_work_session", arguments)
    used = [{"name": "start_work_session", "arguments": arguments, "deterministic": True}]
    try:
        result = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        result = None
    if not isinstance(result, dict) or not (result.get("started") or result.get("resumed") or result.get("already_active")):
        return _response(f"「{selected['task']}」の作業を再開できませんでした。作業状態を確認して再試行してください。",
                         "failed", used, persist=False)
    session = result.get("session")
    if not isinstance(session, dict) or session.get("status") != "active":
        return _response("作業が再開されたことを確認できませんでした。作業状態を確認してください。",
                         "failed", used, persist=False)
    if result.get("already_active"):
        return _response(f"「{selected['task']}」はすでに作業中です。計測を継続しています。", "already_active", used)
    return _response(f"「{selected['task']}」の作業を再開しました。作業時間を計測しています。", "resumed", used)
