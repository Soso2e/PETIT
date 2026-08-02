"""Read-only task-list API for the Universe UI.

The daily briefing intentionally limits and date-filters tasks. Focus and Tasks
need explicit High/Low buckets, while Life Universe needs every open task grouped
under its Project. All reads come from PETIT's local SQLite cache.
"""
from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

from . import db, notifications

_INSTALLED = False
_OPEN_STATUS_SQL = "lower(status) NOT IN ('done', 'canceled', 'cancelled', 'chancel', '完了')"


def list_ui_tasks(priority: str = "high", limit: int = 100) -> JSONResponse:
    normalized = str(priority or "high").strip().casefold()
    if normalized not in {"high", "low", "all"}:
        return JSONResponse(
            {"error": "priorityはhigh、low、allのいずれかを指定してください。"},
            status_code=400,
        )

    from . import task_sync_queue

    task_sync_queue.ensure_task_sync_schema()
    bounded_limit = max(1, min(int(limit), 500))
    where = _OPEN_STATUS_SQL
    params: tuple[Any, ...]
    if normalized == "all":
        params = (bounded_limit,)
    else:
        where += " AND lower(COALESCE(priority, ''))=?"
        params = (normalized, bounded_limit)

    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks_cache "
            f"WHERE {where} "
            "ORDER BY CASE lower(COALESCE(priority, '')) "
            "WHEN 'high' THEN 0 WHEN 'mid' THEN 1 WHEN 'medium' THEN 1 "
            "WHEN 'low' THEN 2 ELSE 3 END, "
            "(due_date IS NULL), due_date ASC, id DESC LIMIT ?",
            params,
        ).fetchall()
    tasks: list[dict[str, Any]] = [dict(row) for row in rows]
    return JSONResponse(
        {
            "tasks": tasks,
            "priority": normalized,
            "count": len(tasks),
        }
    )


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    notifications.router.add_api_route(
        "/tasks",
        list_ui_tasks,
        methods=["GET"],
        tags=["task-ui"],
    )
    _INSTALLED = True
