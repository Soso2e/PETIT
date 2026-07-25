"""Transient Agent progress events delivered through PETIT's existing jobs API."""
from __future__ import annotations

import json
from typing import Any

from . import db, request_context


def emit(
    event: str,
    text: str,
    *,
    tool: str | None = None,
    details: dict[str, Any] | None = None,
    request_id: str | None = None,
    session_id: str | None = None,
) -> None:
    current_request, current_session = request_context.current_ids()
    request_id = request_id or current_request
    session_id = session_id or current_session
    if not session_id:
        return

    payload = {
        "event": str(event or "progress"),
        "text": str(text or "").strip(),
        "tool": tool,
        "details": details or {},
    }
    now = db.now_iso()
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO jobs "
            "(type, status, input_json, result_text, delivered, session_id, request_id, created_at, updated_at) "
            "VALUES ('agent_progress', 'done', '{}', ?, 0, ?, ?, ?, ?)",
            (json.dumps(payload, ensure_ascii=False, default=str), session_id, request_id, now, now),
        )


_TOOL_PROGRESS = {
    "get_lists": "使えるリストを確認してるよ",
    "get_list_items": "リストの中身を確認してるよ",
    "get_tasks": "タスクを確認してるよ",
    "get_schedule": "予定を確認してるよ",
    "get_current_time": "現在時刻を確認してるよ",
    "get_weather": "天気を確認してるよ",
    "search_memory": "過去の記憶を探してるよ",
    "search_brain_notes": "BRAINの関連メモを探してるよ",
    "search_notion": "Notionを確認してるよ",
    "review_github_activity": "GitHubの開発状況を確認してるよ",
    "search_news": "最新情報を調べてるよ",
}


def tool_started(name: str, arguments: dict[str, Any]) -> None:
    emit(
        "tool_started",
        _TOOL_PROGRESS.get(name, f"{name}を使って確認してるよ"),
        tool=name,
        details={"arguments": arguments},
    )


def tool_finished(name: str, *, ok: bool) -> None:
    emit(
        "tool_finished",
        "確認できたよ" if ok else "確認中に問題が起きたよ",
        tool=name,
        details={"ok": ok},
    )
