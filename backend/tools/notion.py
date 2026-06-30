"""Notion integration tools.

sync_notion_tasks: fetches from the configured Notion DB and upserts into
tasks_cache (source='notion'). After syncing, the regular get_tasks tool
returns the fresh data — no need for a separate Notion-specific get tool.

get_tasks (in tasks.py) auto-calls _sync_if_configured() so the LLM only
needs to call one tool.
"""
from __future__ import annotations

from typing import Any

from .. import config, db
from ..notion_client import NotionError, query_database
from .registry import tool


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


def sync_if_configured() -> dict[str, Any] | None:
    """Run a Notion sync silently. Returns a result dict or None if not configured."""
    if not config.notion_configured():
        return None
    try:
        tasks = query_database()
        count = _upsert_tasks(tasks)
        return {"synced": count, "source": "notion"}
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
    if not config.notion_configured():
        return {
            "synced": 0,
            "error": (
                "Notion が設定されていません。"
                "環境変数 NOTION_API_KEY と NOTION_TASKS_DB_ID を設定してください。"
            ),
        }
    try:
        tasks = query_database()
        count = _upsert_tasks(tasks)
        return {"synced": count, "source": "notion", "message": f"{count} 件のタスクを同期しました。"}
    except NotionError as exc:
        return {"synced": 0, "error": str(exc)}
