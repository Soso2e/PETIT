"""Life-first task hierarchy APIs for the Universe UI.

The UI treats every top-level task as a direct child of Life. A top-level task may
act as a project-like parent, with child tasks beneath it. The existing
``project_title`` response field is retained only as a compatibility alias for the
root task title while the original Universe renderer is phased over.
"""
from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import config, db, notifications, task_hierarchy

_INSTALLED = False
_OPEN_STATUS_SQL = "lower(status) NOT IN ('done', 'canceled', 'cancelled', 'chancel', '完了')"
_ALLOWED_PRIORITIES = {"high": "High", "mid": "Mid", "medium": "Mid", "low": "Low"}


class TaskParentUpdate(BaseModel):
    parent_task_id: int | None = None
    move_to_life: bool = False


class ChildTaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    due_date: str | None = None
    priority: str = "High"
    reason: str | None = Field(default=None, max_length=1000)


def _ensure_universe_schema() -> None:
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


def _create_task_record(
    *,
    title: str,
    due_date: str | None,
    priority: str,
    area: str | None,
    reason: str | None,
) -> dict[str, Any]:
    """Load the full task Tool package only when a child creation is executed."""
    from .tools import tasks as task_tools  # noqa: PLC0415

    return task_tools.create_task(
        title=title,
        due_date=due_date,
        priority=priority,
        area=area,
        reason=reason,
    )


def create_child_task(parent_task_id: int, payload: ChildTaskCreate) -> JSONResponse:
    """Create one task and attach it to the selected Life-root task."""
    parent = task_hierarchy._find_task(task_id=parent_task_id)
    if parent is None:
        return JSONResponse({"error": "親Taskが見つかりません。"}, status_code=404)
    if parent.get("parent_task_id") is not None or str(parent.get("parent_external_id") or "").strip():
        return JSONResponse(
            {"error": "子タスクの下には追加できません。Life直下の親Taskを選んでください。"},
            status_code=400,
        )
    if config.notion_configured() and not str(parent.get("external_id") or "").strip():
        return JSONResponse(
            {"error": "Notion同期中は、Notionへ同期済みの親Taskにだけ小タスクを追加できます。"},
            status_code=400,
        )

    values = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
    normalized_priority = _ALLOWED_PRIORITIES.get(str(values.get("priority") or "High").strip().casefold())
    if normalized_priority is None:
        return JSONResponse({"error": "priorityはHigh、Mid、Lowのいずれかです。"}, status_code=400)

    created = _create_task_record(
        title=str(values["title"]).strip(),
        due_date=values.get("due_date"),
        priority=normalized_priority,
        area=parent.get("area"),
        reason=values.get("reason"),
    )
    if not created.get("created"):
        return JSONResponse(created, status_code=400)

    created_task = dict(created.get("task") or {})
    child = None
    external_id = str(created_task.get("external_id") or "").strip()
    local_id = created_task.get("id")
    if external_id:
        child = task_hierarchy._find_task(external_id=external_id)
    if child is None and isinstance(local_id, int):
        child = task_hierarchy._find_task(task_id=local_id)
    if child is None:
        child = task_hierarchy._find_task(title_query=str(values["title"]).strip())
    if child is None:
        return JSONResponse(
            {
                "created": True,
                "linked": False,
                "task": created_task,
                "error": "小タスクは作成されましたが、親Taskへの接続対象を特定できませんでした。",
            },
            status_code=409,
        )

    linked = task_hierarchy.set_task_parent(
        task_id=int(child["id"]),
        parent_task_id=int(parent["id"]),
    )
    if not linked.get("updated"):
        return JSONResponse(
            {
                "created": True,
                "linked": False,
                "task": child,
                "parent": {"id": parent["id"], "title": parent["title"]},
                "error": linked.get("error") or "親Taskへ接続できませんでした。",
            },
            status_code=409,
        )

    return JSONResponse(
        {
            "created": True,
            "linked": True,
            "source": linked.get("source") or created.get("source"),
            "sync_status": linked.get("sync_status") or "synced",
            "task": linked.get("task") or child,
            "parent": {"id": parent["id"], "title": parent["title"]},
            "message": f'「{values["title"]}」を「{parent["title"]}」の小タスクとして追加しました。',
        },
        status_code=201,
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
    notifications.router.add_api_route(
        "/tasks/{task_id}/parent",
        patch_task_parent,
        methods=["PATCH"],
        tags=["task-ui"],
    )
    notifications.router.add_api_route(
        "/tasks/{parent_task_id}/children",
        create_child_task,
        methods=["POST"],
        tags=["task-ui"],
    )
    _INSTALLED = True
