"""Conversation tools for starting, controlling, and reviewing focused work."""
from __future__ import annotations

import re
import unicodedata
from typing import Any
from uuid import uuid4

from .. import config, db, notion_task_sync, work_sessions
from .registry import tool


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or ""))).casefold()


def _task_rows() -> list[dict[str, Any]]:
    notion_task_sync.ensure_schema()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT id, external_id, title, status, project_id, remote_deleted_at FROM tasks_cache "
            "ORDER BY updated_at DESC, id DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def _eligible(row: dict[str, Any]) -> bool:
    terminal = {str(config.NOTION_DONE_STATUS).casefold(), "done", "completed", "完了", "chancel", "cancel", "canceled", "cancelled", "キャンセル", "取消", "取り消し"}
    return not row.get("remote_deleted_at") and str(row.get("status") or "").strip().casefold() not in terminal


def _public_task(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": str(row["id"]),
        "external_id": row.get("external_id"),
        "task": row.get("title"),
        "status": row.get("status"),
        "project_id": row.get("project_id"),
    }


def resolve_task(
    *, task_id: str | None = None, task: str | None = None, allow_partial: bool = True,
) -> dict[str, Any]:
    rows = _task_rows()
    identifier = _normalize(task_id)
    if identifier:
        matches = [
            row
            for row in rows
            if identifier in {_normalize(row.get("id")), _normalize(row.get("external_id"))}
        ]
    else:
        query = _normalize(task)
        if not query:
            return {"error": "作業を開始するタスク名またはtask_idを指定してください。"}
        exact = [row for row in rows if _normalize(row.get("title")) == query]
        matches = exact or ([row for row in rows if query in _normalize(row.get("title"))] if allow_partial else [])
    excluded = [row for row in matches if not _eligible(row)]
    matches = [row for row in matches if _eligible(row)]
    if len(matches) == 1:
        return {"task": _public_task(matches[0])}
    if not matches:
        return {
            "error": "一致したタスクは完了・キャンセル・削除済みのため開始していません。" if excluded else "PETITの保存済みタスク全状態を検索しましたが、一致するタスクが見つかりません。未同期のNotionタスクは未確認です。新規タスクは自動作成していません。",
            "query": task_id or task,
            "excluded": [_public_task(row) for row in excluded[:10]],
            "search_scope": "local_cache_all_states",
        }
    return {
        "error": "複数のタスクが一致しました。task_idで1件を指定してください。",
        "query": task,
        "candidates": [_public_task(row) for row in matches[:10]],
    }


@tool(
    name="get_work_status",
    description=(
        "現在の作業中・一時停止状態、継続時間、今日の合計、タスク別・プロジェクト別内訳を取得する。"
        "『今何を作業中？』『何分続いてる？』『今日どれに何分使った？』で使う。"
    ),
    parameters={"type": "object", "properties": {}},
)
def get_work_status() -> dict[str, Any]:
    return work_sessions.today_summary()


@tool(
    name="get_work_report",
    description=(
        "直近1〜90日の作業記録を日別・タスク別・プロジェクト別に集計する。"
        "今日だけならdays=1、今週や最近7日ならdays=7を使う。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "minimum": 1,
                "maximum": 90,
                "default": 7,
                "description": "今日を含む直近の暦日数。1〜90。",
            }
        },
    },
)
def get_work_report(days: int = 7) -> dict[str, Any]:
    return work_sessions.period_summary(days)


@tool(
    name="start_work_session",
    description=(
        "既存の未完了タスクを選んで作業計測を開始する。task_idを優先し、タスク名は完全一致、"
        "正規化一致、一意な部分一致だけ開始する。0件・複数件なら開始せず候補を返す。"
        "進行中の別セッションがある場合は終了して切り替える。新規タスクは作成しない。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "get_tasksで得たPETIT内部IDまたはNotion external_id。"},
            "task": {"type": "string", "description": "task_idがない場合の既存タスク名。"},
        },
    },
    risk="low_risk_write",
)
def start_work_session(task_id: str | None = None, task: str | None = None) -> dict[str, Any]:
    resolved = resolve_task(task_id=task_id, task=task)
    selected = resolved.get("task")
    if not isinstance(selected, dict):
        return {"started": False, **resolved}

    active = work_sessions.active_session()
    selected_id = str(selected["task_id"])
    previous = active
    new_id = f"chat-{uuid4()}"
    session = work_sessions.start_session(
        new_id,
        str(selected["task"]),
        task_id=selected_id,
        project_id=selected.get("project_id"),
        reuse_task=True,
    )
    if not isinstance(session, dict) or not session.get("session_id") or session.get("status") != "active":
        return {
            "started": False,
            "already_active": False,
            "resumed": False,
            "error": "作業セッションを開始または再開できませんでした。",
        }
    reused = session.get("session_id") != new_id
    return {
        "started": not reused,
        "already_active": reused,
        "resumed": reused and bool(previous and previous.get("status") == "paused"),
        "session": session,
        "replaced_session": previous if previous and not reused else None,
    }


@tool(
    name="update_work_session",
    description=(
        "現在の作業セッションを一時停止、再開、続行確認、終了する。"
        "『休憩する』はpause、『再開する』はresume、『まだ続ける』はcontinue、"
        "『今日はここまで』『作業を終える』はend。タスク自体は完了にしない。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["pause", "resume", "continue", "end"],
                "description": "作業状態の操作。",
            }
        },
        "required": ["action"],
    },
    risk="low_risk_write",
)
def update_work_session(action: str) -> dict[str, Any]:
    active = work_sessions.active_session()
    if not active:
        return {"updated": False, "error": "進行中の作業セッションはありません。"}
    session_id = str(active["session_id"])
    if action == "pause":
        session = work_sessions.pause_session(session_id)
    elif action == "resume":
        session = work_sessions.resume_session(session_id)
    elif action == "end":
        session = work_sessions.end_session(session_id)
    elif action == "continue":
        session = (
            work_sessions.resume_session(session_id)
            if active.get("status") == "paused"
            else work_sessions.respond(session_id)
        )
        if session is None and active.get("status") == "active":
            session = active
    else:
        return {"updated": False, "error": "未対応の作業操作です。"}
    if not session:
        return {"updated": False, "error": "現在の状態ではその操作を実行できません。", "session": active}
    return {"updated": True, "action": action, "session": session}
