"""Notion integration tools.

sync_notion_tasks: fetches from the configured Notion DB and upserts into
tasks_cache (source='notion'). After syncing, the regular get_tasks tool
returns the fresh data — no need for a separate Notion-specific get tool.

get_tasks (in tasks.py) auto-calls _sync_if_configured() so the LLM only
needs to call one tool.
"""
from __future__ import annotations

import time
from typing import Any

from .. import config, db
from ..notion_client import NotionError, query_database
from .registry import tool

_last_sync_monotonic: float | None = None



def _upsert_tasks(tasks: list[dict[str, Any]]) -> int:
    """Upsert a list of parsed Notion pages into tasks_cache.

    Matches on external_id (Notion page UUID). Returns the count upserted.
    """
    now = db.now_iso()
    with db.get_connection() as conn:
        for t in tasks:
            existing = conn.execute(
                "SELECT id FROM tasks_cache WHERE external_id = ?",
                (t["external_id"],),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE tasks_cache SET title=?, status=?, due_date=?, priority=?, "
                    "category=?, reason=?, url=?, done_date=?, updated_at=? "
                    "WHERE external_id=?",
                    (
                        t["title"],
                        t["status"],
                        t["due_date"],
                        t["priority"],
                        t.get("category"),
                        t.get("reason"),
                        t.get("url"),
                        t.get("done_date"),
                        now,
                        t["external_id"],
                    ),
                )
            else:
                conn.execute(
                    "INSERT INTO tasks_cache "
                    "(source, title, status, due_date, priority, category, reason, external_id, url, done_date, updated_at) "
                    "VALUES ('notion', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        t["title"],
                        t["status"],
                        t["due_date"],
                        t["priority"],
                        t.get("category"),
                        t.get("reason"),
                        t["external_id"],
                        t.get("url"),
                        t.get("done_date"),
                        now,
                    ),
                )
    return len(tasks)


def sync_if_configured(force: bool = False) -> dict[str, Any] | None:
    """Refresh Notion with a short TTL so normal chat does not hammer the API."""
    global _last_sync_monotonic
    if not config.notion_configured():
        return None
    now = time.monotonic()
    if (
        not force
        and _last_sync_monotonic is not None
        and now - _last_sync_monotonic < config.NOTION_SYNC_TTL_SECONDS
    ):
        with db.get_connection() as conn:
            cached_count = int(conn.execute("SELECT COUNT(*) FROM tasks_cache WHERE source = 'notion'").fetchone()[0])
        return {"synced": cached_count, "source": "notion", "cached": True}
    try:
        tasks = query_database()
        count = _upsert_tasks(tasks)
        _last_sync_monotonic = now
        return {"synced": count, "source": "notion", "cached": False}
    except NotionError as exc:
        return {"synced": 0, "error": str(exc)}


@tool(
    name="sync_notion_tasks",
    description=(
        "Notion のタスクデータベースを同期し、ローカルキャッシュを最新の状態に更新する。"
        "「Notionを同期して」「最新のタスクを取ってきて」のような発話で使う。"
        "NOTION_API_KEY と NOTION_TASKS_DB_ID が設定されている必要がある。"
    ),
    parameters={"type": "object", "properties": {}},
)
def sync_notion_tasks() -> dict[str, Any]:
    result = sync_if_configured(force=True)
    if result is None:
        return {
            "synced": 0,
            "error": (
                "Notion が設定されていません。"
                "環境変数 NOTION_API_KEY と NOTION_TASKS_DB_ID を設定してください。"
            ),
        }
    if result.get("error"):
        return result
    return {**result, "message": f"{result.get('synced', 0)} 件のタスクを同期しました。"}
