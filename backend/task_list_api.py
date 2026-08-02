"""Read-only task-list API for the Universe UI.

The daily briefing intentionally limits and date-filters tasks. The Universe task
view needs a complete High or Low bucket, so this module exposes only those two
explicit read modes from PETIT's local SQLite cache.
"""
from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

from . import db, notifications

_INSTALLED = False
_OPEN_STATUS_SQL = "lower(status) NOT IN ('done', 'canceled', 'cancelled', 'chancel', '完了')"


def list_ui_tasks(priority: str = "high", limit: int = 100) -> JSONResponse:
    normalized = str(priority or "high").strip().casefold()
    if normalized not in {"high", "low"}:
        return JSONResponse(
            {"error": "priorityはhighまたはlowを指定してください。"},
            status_code=400,
        )

    from . import task_sync_queue

    task_sync_queue.ensure_task_sync_schema()
    bounded_limit = max(1, min(int(limit), 200))
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks_cache "
            f"WHERE {_OPEN_STATUS_SQL} AND lower(COALESCE(priority, ''))=? "
            "ORDER BY (due_date IS NULL), due_date ASC, id DESC LIMIT ?",
            (normalized, bounded_limit),
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
