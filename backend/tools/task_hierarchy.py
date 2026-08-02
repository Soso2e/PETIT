"""Task parent/child hierarchy for the Life-first Universe UI.

A top-level task can act like a project without introducing a separate UI layer.
The hierarchy is intentionally limited to Life -> parent task -> child task.
"""
from __future__ import annotations

import json
from typing import Any

from .. import config, db, notion_client, task_sync_queue
from . import tasks_phase2
from .registry import tool

_PARENT_COLUMN = "parent_task_id"
_ORIGINAL_REMOTE_UPDATE = task_sync_queue._update_remote_task
_PATCH_INSTALLED = False


def ensure_task_hierarchy_schema() -> None:
    task_sync_queue.ensure_task_sync_schema()
    with db.get_connection() as conn:
        columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(tasks_cache)").fetchall()}
        if _PARENT_COLUMN not in columns:
            conn.execute(f'ALTER TABLE tasks_cache ADD COLUMN "{_PARENT_COLUMN}" INTEGER')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_cache_parent_task ON tasks_cache(parent_task_id, status)")


def _effective_parent_id(conn: Any, task: dict[str, Any]) -> int | None:
    external_parent = str(task.get("parent_external_id") or "").strip()
    if task.get("source") == "notion" and external_parent:
        row = conn.execute(
            "SELECT id FROM tasks_cache WHERE source='notion' AND external_id=? LIMIT 1",
            (external_parent,),
        ).fetchone()
        if row:
            return int(row["id"])
    value = task.get("parent_task_id")
    return int(value) if value is not None else None


def _task_has_children(conn: Any, task: dict[str, Any]) -> bool:
    task_id = int(task["id"])
    external_id = str(task.get("external_id") or "").strip()
    row = conn.execute(
        "SELECT 1 FROM tasks_cache WHERE parent_task_id=? "
        "OR (? != '' AND parent_external_id=?) LIMIT 1",
        (task_id, external_id, external_id),
    ).fetchone()
    return row is not None


def _resolve_task(
    task_id: int | str | None = None,
    external_id: str | None = None,
    title_query: str | None = None,
) -> dict[str, Any] | None:
    ensure_task_hierarchy_schema()
    return tasks_phase2._find_task(task_id, external_id, title_query)


def _resolve_parent(
    parent_task_id: int | str | None = None,
    parent_title_query: str | None = None,
) -> dict[str, Any] | None:
    if parent_task_id is not None:
        return _resolve_task(parent_task_id)
    if str(parent_title_query or "").strip():
        return _resolve_task(title_query=parent_title_query)
    return None


def _validate_parent(child: dict[str, Any], parent: dict[str, Any]) -> str | None:
    if int(child["id"]) == int(parent["id"]):
        return "タスク自身を親にはできません。"

    with db.get_connection() as conn:
        if _effective_parent_id(conn, parent) is not None:
            return "親として選べるのはLife直下のタスクだけです。"
        if _task_has_children(conn, child):
            return "子タスクを持つ親タスクは、別の親タスクの下へ移動できません。"

    if child.get("source") == "notion" and not str(parent.get("external_id") or "").strip():
        return "Notionタスクの親には、Notionへ同期済みのタスクだけを選べます。"
    return None


def _remote_parent_payload(parent_external_ids: list[str] | None) -> dict[str, Any]:
    return {config.NOTION_TASK_PROP_PARENT: notion_client._relation_prop(parent_external_ids)}


def _update_remote_task_with_parent(page_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    if "parent_external_ids" not in payload:
        return _ORIGINAL_REMOTE_UPDATE(page_id, payload)

    props = notion_client._task_properties(
        title=payload.get("title"),
        status=payload.get("status"),
        due_date=payload.get("due_date"),
        priority=payload.get("priority"),
        categories=payload.get("categories"),
        area=payload.get("area"),
        project_external_ids=payload.get("project_external_ids"),
        reason=payload.get("reason"),
        done_date=payload.get("done_date"),
    )
    props.update(_remote_parent_payload(payload.get("parent_external_ids")))
    return notion_client.parse_task_page(
        notion_client._patch(f"/pages/{page_id}", {"properties": props}, timeout=20)
    )


def install_parent_sync_support() -> None:
    global _PATCH_INSTALLED
    if _PATCH_INSTALLED:
        return
    task_sync_queue._update_remote_task = _update_remote_task_with_parent
    _PATCH_INSTALLED = True


def set_task_parent(
    *,
    task_id: int | str | None = None,
    external_id: str | None = None,
    title_query: str | None = None,
    parent_task_id: int | str | None = None,
    parent_title_query: str | None = None,
    move_to_life: bool = False,
) -> dict[str, Any]:
    """Move one task under a Life-root task, or detach it back to Life."""
    install_parent_sync_support()
    child = _resolve_task(task_id, external_id, title_query)
    if child is None:
        return {"updated": False, "error": "対象タスクを1件に絞れませんでした。"}

    parent: dict[str, Any] | None = None
    parent_external_ids: list[str] = []
    if not move_to_life:
        parent = _resolve_parent(parent_task_id, parent_title_query)
        if parent is None:
            return {"updated": False, "error": "親タスクを1件に絞れませんでした。"}
        error = _validate_parent(child, parent)
        if error:
            return {"updated": False, "error": error}
        if child.get("source") == "notion":
            parent_external_ids = [str(parent["external_id"])]

    now = db.now_iso()
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE tasks_cache SET parent_task_id=?, parent_external_id=?, parent_external_ids=?, updated_at=? WHERE id=?",
            (
                int(parent["id"]) if parent else None,
                parent_external_ids[0] if parent_external_ids else None,
                json.dumps(parent_external_ids, ensure_ascii=False),
                now,
                int(child["id"]),
            ),
        )

    updated = _resolve_task(int(child["id"])) or child
    if child.get("source") != "notion":
        return {
            "updated": True,
            "source": "local",
            "sync_status": "synced",
            "task": updated,
            "parent": {"id": parent["id"], "title": parent["title"]} if parent else None,
            "message": f"タスクを{'Life直下へ戻しました' if parent is None else f'「{parent["title"]}」の子タスクにしました'}。",
        }

    operation_id = task_sync_queue.enqueue_update(
        int(child["id"]),
        {"parent_external_ids": parent_external_ids},
        base_source_updated_at=child.get("source_updated_at"),
    )
    updated = _resolve_task(int(child["id"])) or updated
    return {
        "updated": True,
        "source": "notion",
        "queued": True,
        "sync_status": "pending",
        "operation_id": operation_id,
        "task": updated,
        "parent": {"id": parent["id"], "title": parent["title"]} if parent else None,
        "message": f"タスクを{'Life直下へ戻し' if parent is None else f'「{parent["title"]}」の子タスクにし'}、Notion同期へ追加しました。",
    }


@tool(
    name="set_task_parent",
    description=(
        "既存タスクを別のタスクの子にする、またはLife直下へ戻す。"
        "『XをPETIT開発の子タスクにして』『XをLife直下へ戻して』のような依頼で使う。"
        "親として選べるのはLife直下のタスクだけ。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "task_id": {"type": "integer"},
            "external_id": {"type": "string"},
            "title_query": {"type": "string"},
            "parent_task_id": {"type": "integer"},
            "parent_title_query": {"type": "string"},
            "move_to_life": {"type": "boolean", "default": False},
        },
    },
    requires_confirmation=True,
)
def set_task_parent_tool(
    task_id: int | str | None = None,
    external_id: str | None = None,
    title_query: str | None = None,
    parent_task_id: int | str | None = None,
    parent_title_query: str | None = None,
    move_to_life: bool = False,
) -> dict[str, Any]:
    return set_task_parent(
        task_id=task_id,
        external_id=external_id,
        title_query=title_query,
        parent_task_id=parent_task_id,
        parent_title_query=parent_title_query,
        move_to_life=move_to_life,
    )


install_parent_sync_support()
