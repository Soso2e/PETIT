"""Deterministic task resolution for conversational completion reports.

Named reports such as ``LiTデザインは完了した`` should resolve against the
local task cache before the broader project-completion flow or an LLM agent.
The actual write still goes through PETIT's existing confirmation boundary.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any

from . import config, db

_DRAFT_TTL_MINUTES = 30
_NAMED_COMPLETION_PATTERNS = (
    re.compile(
        r"^(?P<title>.+?)(?:は|が|を)?(?:もう)?"
        r"(?:完了した|完了したよ|完了|終わった|終えた|できた)"
        r"(?:よ|ね|ぞ|！|!|。|\.)*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?P<title>.+?)(?:という)?(?:タスク)?を?"
        r"(?:完了にして|完了扱いにして|終わりにして)"
        r"(?:ください|ほしい|ね|！|!|。|\.)*$",
        re.IGNORECASE,
    ),
)
_GENERIC_TARGETS = {
    "これ",
    "それ",
    "あれ",
    "全部",
    "すべて",
    "作業",
    "実装",
    "テスト",
    "確認",
    "今日",
    "このタスク",
    "タスク",
}
_CANCEL_REPLIES = {"やめる", "やめて", "キャンセル", "取消", "取り消し", "しない"}
_DONE_STATUSES = {"done", "completed", "complete", "完了"}
_CANCELLED_STATUSES = {"cancelled", "canceled", "chancel", "cancel", "キャンセル", "中止"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS task_completion_drafts (
    user_id TEXT PRIMARY KEY,
    query_text TEXT NOT NULL,
    candidate_ids_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
"""


def ensure_schema() -> None:
    with db.get_connection() as conn:
        conn.executescript(_SCHEMA)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = text.replace("ライフイズテック", "lit").replace("life is tech", "lit")
    text = text.replace("リット", "lit")
    text = re.sub(r"(?:という)?タスク$", "", text)
    text = re.sub(r"[\s\u3000、。,.!！?？『』「」\"'・_\-/]", "", text)
    return text.replace("の", "")


def _extract_title(message: str) -> str | None:
    text = " ".join(str(message or "").strip().split())
    if not text or "プロジェクト" in text:
        return None
    for pattern in _NAMED_COMPLETION_PATTERNS:
        match = pattern.fullmatch(text)
        if not match:
            continue
        title = match.group("title").strip(" \t\r\n、,。.!！?？『』「」\"'")
        title = re.sub(r"^(?:この|その|あの)\s*", "", title).strip()
        if title in _GENERIC_TARGETS or _normalize(title) in {_normalize(item) for item in _GENERIC_TARGETS}:
            return None
        if len(_normalize(title)) < 3 or len(title) > 120:
            return None
        return title
    return None


def _status_kind(status: Any) -> str:
    normalized = str(status or "").strip().casefold()
    configured_done = str(config.NOTION_DONE_STATUS or "Done").strip().casefold()
    if normalized in _DONE_STATUSES | {configured_done}:
        return "done"
    if normalized in _CANCELLED_STATUSES:
        return "cancelled"
    return "active"


def _score(query: str, title: str) -> float:
    normalized_query = _normalize(query)
    normalized_title = _normalize(title)
    if not normalized_query or not normalized_title:
        return 0.0
    if normalized_query == normalized_title:
        return 1.0
    if normalized_query in normalized_title:
        return 0.92
    if normalized_title in normalized_query:
        return 0.88
    return SequenceMatcher(None, normalized_query, normalized_title).ratio()


def _task_rows() -> list[dict[str, Any]]:
    ensure_schema()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT id, title, status, due_date, priority, source "
            "FROM tasks_cache ORDER BY id DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def _ranked_candidates(query: str) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for task in _task_rows():
        score = _score(query, str(task.get("title") or ""))
        if score < 0.62:
            continue
        ranked.append({**task, "match_score": round(score, 3), "status_kind": _status_kind(task.get("status"))})
    ranked.sort(
        key=lambda item: (
            item["status_kind"] != "active",
            -float(item["match_score"]),
            -int(item["id"]),
        )
    )
    return ranked


def _confident_group(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not candidates:
        return []
    top_score = float(candidates[0]["match_score"])
    if top_score < 0.72:
        return []
    return [item for item in candidates if top_score - float(item["match_score"]) <= 0.08][:5]


def _save_draft(user_id: str, query: str, candidates: list[dict[str, Any]]) -> None:
    ensure_schema()
    now = _utc_now()
    expires = now + timedelta(minutes=_DRAFT_TTL_MINUTES)
    ids = [int(item["id"]) for item in candidates[:5]]
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO task_completion_drafts "
            "(user_id, query_text, candidate_ids_json, created_at, expires_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET query_text=excluded.query_text, "
            "candidate_ids_json=excluded.candidate_ids_json, created_at=excluded.created_at, "
            "expires_at=excluded.expires_at",
            (user_id, query, json.dumps(ids), now.isoformat(), expires.isoformat()),
        )


def _clear_draft(user_id: str) -> None:
    ensure_schema()
    with db.get_connection() as conn:
        conn.execute("DELETE FROM task_completion_drafts WHERE user_id=?", (user_id,))


def _get_draft_candidates(user_id: str) -> list[dict[str, Any]]:
    ensure_schema()
    with db.get_connection() as conn:
        draft = conn.execute(
            "SELECT candidate_ids_json, expires_at FROM task_completion_drafts WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if not draft:
            return []
        try:
            expired = datetime.fromisoformat(str(draft["expires_at"])) <= _utc_now()
            ids = [int(value) for value in json.loads(str(draft["candidate_ids_json"]))]
        except (ValueError, TypeError, json.JSONDecodeError):
            expired, ids = True, []
        if expired or not ids:
            conn.execute("DELETE FROM task_completion_drafts WHERE user_id=?", (user_id,))
            return []
        placeholders = ", ".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT id, title, status, due_date, priority, source "
            f"FROM tasks_cache WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
    by_id = {int(row["id"]): dict(row) for row in rows}
    return [by_id[task_id] for task_id in ids if task_id in by_id]


def _preview(task: dict[str, Any], *, selected_from_draft: bool = False) -> dict[str, Any]:
    title = str(task.get("title") or "名称未設定")
    return {
        "reply": f"おつかれさま！「{title}」だね。完了に反映していい？",
        "used_tools": [],
        "pending_actions": [
            {
                "name": "complete_task",
                "arguments": {"task_id": int(task["id"]), "title_query": title},
            }
        ],
        "persist": True,
        "model_route": {
            "kind": "task_completion_preview",
            "requested_route": "deterministic",
            "actual_route": "deterministic",
            "model": None,
            "task_id": int(task["id"]),
            "selected_from_draft": selected_from_draft,
        },
    }


def _candidate_reply(candidates: list[dict[str, Any]]) -> str:
    lines = ["近い未完了タスクが複数あるよ。どれを完了にする？"]
    for index, task in enumerate(candidates, start=1):
        lines.append(f"{index}. {task['title']}")
    lines.append("番号か名前で教えて。")
    return "\n".join(lines)


def _resolve_draft_reply(message: str, *, user_id: str) -> dict[str, Any] | None:
    candidates = _get_draft_candidates(user_id)
    if not candidates:
        return None
    text = str(message or "").strip()
    if _normalize(text) in {_normalize(item) for item in _CANCEL_REPLIES}:
        _clear_draft(user_id)
        return {
            "reply": "了解。タスクの完了反映はやめておくね。",
            "used_tools": [],
            "persist": True,
            "model_route": {"kind": "task_completion_cancelled", "model": None},
        }

    selected: dict[str, Any] | None = None
    if re.fullmatch(r"[1-9]", text):
        index = int(text) - 1
        if index < len(candidates):
            selected = candidates[index]
    if selected is None:
        normalized = _normalize(text)
        matches = [task for task in candidates if normalized and (
            normalized == _normalize(str(task["title"]))
            or normalized in _normalize(str(task["title"]))
        )]
        if len(matches) == 1:
            selected = matches[0]
    if selected is not None:
        _clear_draft(user_id)
        return _preview(selected, selected_from_draft=True)
    return {
        "reply": _candidate_reply(candidates),
        "used_tools": [],
        "persist": True,
        "model_route": {"kind": "task_completion_candidates", "model": None},
    }


def try_handle_task_completion_turn(
    message: str,
    *,
    user_id: str,
    recent_history: list[dict[str, str]] | None = None,
) -> dict[str, Any] | None:
    """Resolve a named task completion without entering the Agent tool loop."""
    del recent_history
    draft_result = _resolve_draft_reply(message, user_id=user_id)
    if draft_result:
        return draft_result

    query = _extract_title(message)
    if query is None:
        return None
    candidates = _ranked_candidates(query)
    active = _confident_group([item for item in candidates if item["status_kind"] == "active"])
    if len(active) == 1:
        return _preview(active[0])
    if len(active) > 1:
        _save_draft(user_id, query, active)
        return {
            "reply": _candidate_reply(active),
            "used_tools": [],
            "persist": True,
            "model_route": {
                "kind": "task_completion_candidates",
                "requested_route": "deterministic",
                "actual_route": "deterministic",
                "model": None,
                "candidate_count": len(active),
            },
        }

    done = _confident_group([item for item in candidates if item["status_kind"] == "done"])
    if len(done) == 1:
        return {
            "reply": f"「{done[0]['title']}」は、すでに完了になっているよ。",
            "used_tools": [],
            "persist": True,
            "model_route": {
                "kind": "task_completion_already_done",
                "requested_route": "deterministic",
                "actual_route": "deterministic",
                "model": None,
                "task_id": int(done[0]["id"]),
            },
        }

    # A named active project still belongs to Project Continuity when no task
    # candidate matched. Task matches above deliberately keep priority because
    # task titles often contain their project name.
    from . import project_continuity

    active_project = project_continuity.get_active_project(user_id)
    if active_project:
        project_name = _normalize(str(active_project.get("name") or ""))
        normalized_query = _normalize(query)
        if project_name and (project_name in normalized_query or normalized_query in project_name):
            return None

    return {
        "reply": f"「{query}」に近い未完了タスクは見つからなかったよ。別の名前で登録されている？",
        "used_tools": [],
        "persist": True,
        "model_route": {
            "kind": "task_completion_not_found",
            "requested_route": "deterministic",
            "actual_route": "deterministic",
            "model": None,
        },
    }
