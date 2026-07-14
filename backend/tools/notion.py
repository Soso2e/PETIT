"""Notion task synchronization with durable freshness/error state."""
from __future__ import annotations

import time
from typing import Any

from .. import config, db
from ..notion_client import NotionError, query_database
from .registry import tool

_last_sync_monotonic: float | None = None


def _safe_error(exc: Exception) -> str:
    text = str(exc)
    for secret in (config.NOTION_API_KEY, config.NOTION_TASKS_DB_ID):
        if secret:
            text = text.replace(secret, "[redacted]")
    return text[:300] or "Notion の同期に失敗しました"


def _upsert_tasks(tasks: list[dict[str, Any]]) -> int:
    now = db.now_iso()
    with db.get_connection() as conn:
        for t in tasks:
            existing = conn.execute("SELECT id FROM tasks_cache WHERE external_id = ?", (t["external_id"],)).fetchone()
            if existing:
                conn.execute("UPDATE tasks_cache SET title=?, status=?, due_date=?, priority=?, category=?, reason=?, url=?, done_date=?, updated_at=? WHERE external_id=?",
                    (t["title"], t["status"], t["due_date"], t["priority"], t.get("category"), t.get("reason"), t.get("url"), t.get("done_date"), now, t["external_id"]))
            else:
                conn.execute("INSERT INTO tasks_cache (source, title, status, due_date, priority, category, reason, external_id, url, done_date, updated_at) VALUES ('notion', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (t["title"], t["status"], t["due_date"], t["priority"], t.get("category"), t.get("reason"), t["external_id"], t.get("url"), t.get("done_date"), now))
    return len(tasks)


def _result(ok: bool, count: int, cached: bool, error: str | None = None) -> dict[str, Any]:
    state = db.sync_state("notion")
    with db.get_connection() as conn:
        has_cache = bool(conn.execute("SELECT 1 FROM tasks_cache WHERE source = 'notion' LIMIT 1").fetchone())
    return {"ok": ok, "source": "notion", "synced_count": count, "cached": bool(cached or (not ok and has_cache)),
            "stale": bool(not ok and state["last_success_at"]), "last_synced_at": state["last_success_at"], "error": error}


def status() -> dict[str, Any]:
    state = db.sync_state("notion")
    return {"configured": config.notion_configured(), "last_synced_at": state["last_success_at"],
            "last_failed_at": state["last_failure_at"], "synced_count": state["synced_count"],
            "error": state["last_error"], "stale": bool(state["last_failure_at"] and state["last_success_at"])}


def sync_if_configured(force: bool = False) -> dict[str, Any]:
    global _last_sync_monotonic
    if not config.notion_configured():
        return _result(False, 0, False, "Notion が設定されていません") | {"configured": False}
    if not force and _last_sync_monotonic is not None and time.monotonic() - _last_sync_monotonic < config.NOTION_SYNC_TTL_SECONDS:
        with db.get_connection() as conn:
            count = int(conn.execute("SELECT COUNT(*) FROM tasks_cache WHERE source = 'notion'").fetchone()[0])
        return _result(True, count, True) | {"configured": True}
    try:
        count = _upsert_tasks(query_database())
        at = db.record_sync_success("notion", count)
        _last_sync_monotonic = time.monotonic()
        return {"ok": True, "source": "notion", "synced_count": count, "cached": False, "stale": False,
                "last_synced_at": at, "error": None, "configured": True}
    except NotionError as exc:
        error = _safe_error(exc)
        db.record_sync_failure("notion", error)
        return _result(False, 0, False, error) | {"configured": True}


@tool(name="sync_notion_tasks", description="Notion のタスクデータベースを同期し、状態とキャッシュを更新する。", parameters={"type": "object", "properties": {}})
def sync_notion_tasks() -> dict[str, Any]:
    return sync_if_configured(force=True)
