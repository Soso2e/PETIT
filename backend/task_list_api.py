"""Life-first task hierarchy APIs for the Universe UI.

The UI treats every top-level task as a direct child of Life. A top-level task may
act as a project-like parent, with child tasks beneath it. The existing
``project_title`` response field is retained only as a compatibility alias for the
root task title while the original Universe renderer is phased over.
"""
from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import db, notifications

_INSTALLED = False
_OPEN_STATUS_SQL = "lower(status) NOT IN ('done', 'canceled', 'cancelled', 'chancel', '完了')"


class TaskParentUpdate(BaseModel):
    parent_task_id: int | None = None
    move_to_life: bool = False


def _ensure_universe_schema() -> None:
    from .tools import task_hierarchy

    task_hierarchy.ensure_task_hierarchy_schema()


def _open_rows() -> list[dict[str, Any]]:
    _ensure_universe_schema()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks_cache "
            f"WHERE {_OPEN_STATUS_SQL} "
            "ORDER BY CASE lower(COALESCE(priority, '')) "
            "WHEN 'high' THEN 0 WHEN 'mid' THEN 1 WHEN 'medium' THEN 1 "
            "WHEN 'low' THEN 2 ELSE 3 END, "
            "(due_date IS NULL), due_date ASC, id DESC",
            (),
        ).fetchall()
    return [dict(row) for row in rows]


def _annotate_hierarchy(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {int(task["id"]): task for task in tasks if task.get("id") is not None}
    by_external = {
        str(task["external_id"]): task
        for task in tasks
        if str(task.get("external_id") or "").strip()
    }

    parent_ids: dict[int, int | None] = {}
    for task in tasks:
        task_id = int(task["id"])
        parent_id: int | None = None
        external_parent = str(task.get("parent_external_id") or "").strip()
        if task.get("source") == "notion" and external_parent:
            parent = by_external.get(external_parent)
            if parent:
                parent_id = int(parent["id"])
        if parent_id is None and task.get("parent_task_id") is not None:
            candidate = int(task["parent_task_id"])
            if candidate in by_id:
                parent_id = candidate
        if parent_id == task_id:
            parent_id = None
        parent_ids[task_id] = parent_id

    child_counts: dict[int, int] = {task_id: 0 for task_id in by_id}
    for parent_id in parent_ids.values():
        if parent_id in child_counts:
            child_counts[parent_id] += 1

    annotated: list[dict[str, Any]] = []
    for task in tasks:
        task_id = int(task["id"])
        parent_id = parent_ids.get(task_id)
        parent = by_id.get(parent_id) if parent_id is not None else None
        root = parent or task
        root_id = int(root["id"])
        root_title = str(root.get("title") or "名称未設定タスク")
        annotated.append(
            {
                **task,
                "parent_task_id": parent_id,
                "parent_title": str(parent.get("title") or "") if parent else None,
                "root_task_id": root_id,
                "root_title": root_title,
                "project_title": root_title,
                "hierarchy_role": "child" if parent else "root",
                "depth": 1 if parent else 0,
                "child_count": child_counts.get(task_id, 0),
                "has_children": child_counts.get(task_id, 0) > 0,
            }
        )

    return annotated


def list_ui_tasks(priority: str = "high", limit: int = 100) -> JSONResponse:
    normalized = str(priority or "high").strip().casefold()
    if normalized not in {"high", "low", "all"}:
        return JSONResponse(
            {"error": "priorityはhigh、low、allのいずれかを指定してください。"},
            status_code=400,
        )

    tasks = _annotate_hierarchy(_open_rows())
    if normalized != "all":
        tasks = [task for task in tasks if str(task.get("priority") or "").casefold() == normalized]
    bounded_limit = max(1, min(int(limit), 500))
    tasks = tasks[:bounded_limit]
    roots = [task for task in tasks if task.get("hierarchy_role") == "root"]
    return JSONResponse(
        {
            "tasks": tasks,
            "priority": normalized,
            "count": len(tasks),
            "root_count": len(roots),
            "hierarchy": "life-task-child",
        }
    )


def patch_task_parent(task_id: int, payload: TaskParentUpdate) -> JSONResponse:
    from .tools import task_hierarchy

    values = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
    parent_task_id = values.get("parent_task_id")
    move_to_life = bool(values.get("move_to_life"))
    if parent_task_id is None and not move_to_life:
        return JSONResponse({"error": "parent_task_idまたはmove_to_lifeを指定してください。"}, status_code=400)
    result = task_hierarchy.set_task_parent(
        task_id=task_id,
        parent_task_id=parent_task_id,
        move_to_life=move_to_life,
    )
    return JSONResponse(result, status_code=200 if result.get("updated") else 400)


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
        "/tasks/{task_id}/parent",
        patch_task_parent,
        methods=["PATCH"],
        tags=["task-ui"],
    )
    _INSTALLED = True
