"""Task and project read APIs for the Universe UI.

The daily briefing intentionally limits and date-filters tasks. Focus and Tasks
need explicit High/Low buckets, while Life Universe needs every open task grouped
under its Project. All reads come from PETIT's local SQLite cache.
"""
from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

from . import db, notifications

_INSTALLED = False
_OPEN_STATUS_SQL = "lower(t.status) NOT IN ('done', 'canceled', 'cancelled', 'chancel', '完了')"
_ALL_PROJECT_LABEL = "All"


def _ensure_universe_schema() -> None:
    from . import notion_project_sync

    notion_project_sync.ensure_notion_project_schema()


def list_ui_tasks(priority: str = "high", limit: int = 100) -> JSONResponse:
    normalized = str(priority or "high").strip().casefold()
    if normalized not in {"high", "low", "all"}:
        return JSONResponse(
            {"error": "priorityはhigh、low、allのいずれかを指定してください。"},
            status_code=400,
        )

    _ensure_universe_schema()
    bounded_limit = max(1, min(int(limit), 500))
    where = _OPEN_STATUS_SQL
    params: tuple[Any, ...]
    if normalized == "all":
        params = (bounded_limit,)
    else:
        where += " AND lower(COALESCE(t.priority, ''))=?"
        params = (normalized, bounded_limit)

    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT t.*, COALESCE(NULLIF(TRIM(p.name), ''), ?) AS project_title "
            "FROM tasks_cache t LEFT JOIN projects p ON p.id=t.project_id "
            f"WHERE {where} "
            "ORDER BY CASE lower(COALESCE(t.priority, '')) "
            "WHEN 'high' THEN 0 WHEN 'mid' THEN 1 WHEN 'medium' THEN 1 "
            "WHEN 'low' THEN 2 ELSE 3 END, "
            "(t.due_date IS NULL), t.due_date ASC, t.id DESC LIMIT ?",
            (_ALL_PROJECT_LABEL, *params),
        ).fetchall()
    tasks: list[dict[str, Any]] = [dict(row) for row in rows]
    return JSONResponse(
        {
            "tasks": tasks,
            "priority": normalized,
            "count": len(tasks),
            "unassigned_label": _ALL_PROJECT_LABEL,
        }
    )


def list_ui_projects() -> JSONResponse:
    """Return selectable internal projects and whether Notion Relation is confirmed."""
    _ensure_universe_schema()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT p.id, p.name, p.status, p.description, "
            "EXISTS(SELECT 1 FROM project_source_links l "
            "WHERE l.project_id=p.id AND l.provider='notion' AND l.status='active' "
            "AND l.confirmed_at IS NOT NULL) AS notion_linked "
            "FROM projects p WHERE p.status!='archived' "
            "ORDER BY CASE p.status WHEN 'active' THEN 0 ELSE 1 END, p.updated_at DESC, p.name ASC",
            (),
        ).fetchall()
    projects = [
        {
            **dict(row),
            "notion_linked": bool(row["notion_linked"]),
        }
        for row in rows
    ]
    return JSONResponse({"projects": projects, "count": len(projects)})


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
    notifications.router.add_api_route(
        "/projects",
        list_ui_projects,
        methods=["GET"],
        tags=["task-ui"],
    )
    _INSTALLED = True
