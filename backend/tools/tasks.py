"""Task tools.

MVP reads/writes a local SQLite task cache. The Concept calls for Notion as a
source later; when that lands, it can populate tasks_cache (source='notion')
and this tool keeps working unchanged.
"""
from __future__ import annotations

from typing import Any

from .. import db
from .registry import tool


@tool(
    name="get_tasks",
    description=(
        "保存されているタスク一覧を取得する。"
        "「今日のタスク教えて」「やること何があったっけ」のような発話で使う。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "description": "絞り込むステータス（例: todo, doing, done）。省略で全件。",
            },
            "limit": {"type": "integer", "description": "最大件数", "default": 20},
        },
    },
)
def get_tasks(status: str | None = None, limit: int = 20) -> dict[str, Any]:
    sql = "SELECT id, source, title, status, due_date, priority FROM tasks_cache"
    params: list[Any] = []
    if status:
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY (due_date IS NULL), due_date ASC LIMIT ?"
    params.append(limit)
    with db.get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    tasks = [dict(r) for r in rows]
    return {"count": len(tasks), "tasks": tasks}


@tool(
    name="add_task",
    description="新しいタスクをローカルに追加する。「○○をタスクに入れて」のような発話で使う。",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "タスクの内容"},
            "due_date": {"type": "string", "description": "期限（YYYY-MM-DD 等）。任意。"},
            "priority": {"type": "string", "description": "優先度（例: high, mid, low）。任意。"},
        },
        "required": ["title"],
    },
)
def add_task(title: str, due_date: str | None = None, priority: str | None = None) -> dict[str, Any]:
    with db.get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO tasks_cache (source, title, status, due_date, priority, updated_at) "
            "VALUES ('local', ?, 'todo', ?, ?, ?)",
            (title, due_date, priority, db.now_iso()),
        )
        task_id = int(cur.lastrowid)
    return {"added": True, "id": task_id, "title": title, "due_date": due_date, "priority": priority}
