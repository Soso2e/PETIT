"""Phase 2 task tools with optimistic local writes and durable Notion sync."""
from __future__ import annotations

import json
from datetime import date
from typing import Any

from .. import config, db, project_continuity, task_sync_queue
from ..task_taxonomy import AREAS, AREA_LABELS, resolve_area
from . import tasks as legacy_tasks
from .registry import tool

_CATEGORIES = ["JobHunt", "Sch", "Life", "Work", "Hobby", "Event", "Create", "LiT"]
_PRIORITIES = ["Low", "Mid", "High"]
_AGENT_ROUTES_INSTALLED = False

# Replace the Notion cache merge with the conflict-aware Phase 2 implementation.
task_sync_queue.install_sync_guard()


def _normalize_task_id(task_id: int | str | None, external_id: str | None) -> tuple[int | None, str | None]:
    if isinstance(task_id, str) and not task_id.isdigit():
        return None, external_id or task_id
    if isinstance(task_id, str):
        return int(task_id), external_id
    return task_id, external_id


def _find_task(
    task_id: int | str | None = None,
    external_id: str | None = None,
    title_query: str | None = None,
) -> dict[str, Any] | None:
    task_sync_queue.ensure_task_sync_schema()
    normalized_id, external_id = _normalize_task_id(task_id, external_id)
    with db.get_connection() as conn:
        if normalized_id is not None:
            row = conn.execute("SELECT * FROM tasks_cache WHERE id=?", (normalized_id,)).fetchone()
            return dict(row) if row else None
        if external_id:
            row = conn.execute("SELECT * FROM tasks_cache WHERE external_id=?", (external_id,)).fetchone()
            return dict(row) if row else None
        if title_query:
            rows = conn.execute(
                "SELECT * FROM tasks_cache WHERE title LIKE ? "
                "ORDER BY (status = ?) ASC, (due_date IS NULL), due_date ASC, id DESC LIMIT 2",
                (f"%{title_query}%", config.NOTION_DONE_STATUS),
            ).fetchall()
            if len(rows) == 1:
                return dict(rows[0])
    return None


def _candidates(title_query: str | None) -> list[dict[str, Any]]:
    if not title_query:
        return []
    task_sync_queue.ensure_task_sync_schema()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT id, title, status, due_date, area, project_id, source, sync_status "
            "FROM tasks_cache WHERE title LIKE ? ORDER BY id DESC LIMIT 5",
            (f"%{title_query}%",),
        ).fetchall()
    return [dict(row) for row in rows]


def _validate_project(project_id: str | None) -> tuple[bool, str | None, list[str] | None]:
    if not project_id:
        return True, None, None
    project_continuity.ensure_project_schema()
    if project_continuity.get_project(project_id) is None:
        return False, "指定されたPETIT内部プロジェクトが見つかりません。", None
    try:
        external_id = legacy_tasks._confirmed_notion_project_external_id(project_id)
    except ValueError as exc:
        return False, str(exc), None
    return True, None, [external_id]


def _insert_task(
    *,
    source: str,
    title: str,
    status: str,
    due_date: str | None,
    priority: str | None,
    area: str | None,
    project_id: str | None,
    project_external_ids: list[str] | None,
    category: str | None,
    reason: str | None,
    done_date: str | None = None,
    sync_status: str = "synced",
) -> dict[str, Any]:
    task_sync_queue.ensure_task_sync_schema()
    now = db.now_iso()
    external_ids = project_external_ids or []
    with db.get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO tasks_cache "
            "(source, title, status, due_date, priority, area, project_id, project_external_id, "
            "project_external_ids, category, reason, done_date, sync_status, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                source,
                title,
                status,
                due_date,
                priority,
                area,
                project_id,
                external_ids[0] if external_ids else None,
                json.dumps(external_ids, ensure_ascii=False),
                category,
                reason,
                done_date,
                sync_status,
                now,
            ),
        )
        task_id = int(cur.lastrowid)
    return {
        "id": task_id,
        "source": source,
        "title": title,
        "status": status,
        "due_date": due_date,
        "priority": priority,
        "area": area,
        "project_id": project_id,
        "project_external_id": external_ids[0] if external_ids else None,
        "category": category,
        "reason": reason,
        "done_date": done_date,
        "sync_status": sync_status,
    }


def _notion_create_payload(
    *,
    title: str,
    due_date: str | None,
    priority: str,
    category: str | None,
    area: str | None,
    project_external_ids: list[str] | None,
    reason: str | None,
    status: str,
) -> dict[str, Any]:
    return {
        "title": title,
        "due_date": due_date,
        "priority": priority,
        "categories": [category] if category else None,
        "area": AREA_LABELS[area] if area else None,
        "project_external_ids": project_external_ids,
        "reason": reason,
        "status": status,
    }


@tool(
    name="get_tasks",
    description=(
        "SQLiteのタスクミラーから即時に一覧を取得する。Notion同期は会話を待たせず、"
        "sync_statusでpending/synced/failed/conflictを確認できる。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "省略で未完了、allで全件。"},
            "area": {"type": "string", "enum": list(AREAS)},
            "project_id": {"type": "string"},
            "sync_status": {"type": "string", "enum": list(task_sync_queue.SYNC_STATES)},
            "limit": {"type": "integer", "default": 20},
        },
    },
)
def get_tasks(
    status: str | None = None,
    area: str | None = None,
    project_id: str | None = None,
    sync_status: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    task_sync_queue.ensure_task_sync_schema()
    normalized_area, _ = resolve_area(area)
    sql = (
        "SELECT id, source, title, status, due_date, priority, category, area, reason, url, done_date, "
        "project_id, project_external_id, external_id, sync_status, sync_error, sync_operation_id, "
        "sync_attempts, last_synced_at FROM tasks_cache"
    )
    conditions: list[str] = []
    params: list[Any] = []
    if status and status.casefold() != "all":
        conditions.append("status=?")
        params.append(status)
    elif not status:
        conditions.append("status!=?")
        params.append(config.NOTION_DONE_STATUS)
    if normalized_area:
        conditions.append("area=?")
        params.append(normalized_area)
    if project_id:
        conditions.append("project_id=?")
        params.append(project_id)
    if sync_status in task_sync_queue.SYNC_STATES:
        conditions.append("sync_status=?")
        params.append(sync_status)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY (due_date IS NULL), due_date ASC, id DESC LIMIT ?"
    params.append(max(1, min(int(limit), 100)))
    with db.get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return {
        "count": len(rows),
        "tasks": [dict(row) for row in rows],
        "filters": {
            "status": status,
            "area": normalized_area,
            "project_id": project_id,
            "sync_status": sync_status,
        },
        "write_queue": task_sync_queue.status(limit=5),
    }


@tool(
    name="create_task",
    description=(
        "新しいタスクを作成する。Notion設定時は承認後すぐSQLiteへ保存し、Notion書き込みは"
        "pendingキューでバックグラウンド実行する。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "due_date": {"type": "string"},
            "priority": {"type": "string", "enum": _PRIORITIES},
            "area": {"type": "string", "enum": list(AREAS)},
            "project_id": {"type": "string"},
            "category": {"type": "string", "enum": _CATEGORIES},
            "reason": {"type": "string"},
        },
        "required": ["title"],
    },
    requires_confirmation=True,
)
def create_task(
    title: str,
    due_date: str | None = None,
    priority: str | None = None,
    area: str | None = None,
    project_id: str | None = None,
    category: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    title = str(title or "").strip()
    if not title:
        return {"created": False, "error": "タスク名が空です。"}
    priority = legacy_tasks._normalize_option(priority, _PRIORITIES) or "Mid"
    category, category_source = legacy_tasks._resolve_category(title, category, reason)
    area, area_source = resolve_area(area, category)

    project_external_ids: list[str] | None = None
    if project_id:
        if config.notion_configured():
            valid, error, project_external_ids = _validate_project(project_id)
        else:
            project_continuity.ensure_project_schema()
            valid = project_continuity.get_project(project_id) is not None
            error = None if valid else "指定されたPETIT内部プロジェクトが見つかりません。"
        if not valid:
            return {"created": False, "error": error, "project_id": project_id}

    if not config.notion_configured():
        task = _insert_task(
            source="local",
            title=title,
            status=config.NOTION_DEFAULT_STATUS,
            due_date=due_date,
            priority=priority,
            area=area,
            project_id=project_id,
            project_external_ids=None,
            category=category,
            reason=reason,
        )
        return {
            "created": True,
            "source": "local",
            "task": task,
            "area_source": area_source,
            "category_source": category_source,
        }

    task = _insert_task(
        source="notion",
        title=title,
        status=config.NOTION_DEFAULT_STATUS,
        due_date=due_date,
        priority=priority,
        area=area,
        project_id=project_id,
        project_external_ids=project_external_ids,
        category=category,
        reason=reason,
        sync_status="pending",
    )
    operation_id = task_sync_queue.enqueue_create(
        int(task["id"]),
        _notion_create_payload(
            title=title,
            due_date=due_date,
            priority=priority,
            category=category,
            area=area,
            project_external_ids=project_external_ids,
            reason=reason,
            status=config.NOTION_DEFAULT_STATUS,
        ),
    )
    task["sync_operation_id"] = operation_id
    return {
        "created": True,
        "source": "notion",
        "queued": True,
        "sync_status": "pending",
        "operation_id": operation_id,
        "task": task,
        "area_source": area_source,
        "category_source": category_source,
        "message": "ローカルへ保存し、Notion同期をキューへ追加しました。",
    }


def _update_payload(
    *,
    title: str | None,
    status: str | None,
    due_date: str | None,
    priority: str | None,
    area: str | None,
    project_external_ids: list[str] | None,
    category: str | None,
    reason: str | None,
    done_date: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if title is not None:
        payload["title"] = title
    if status is not None:
        payload["status"] = status
    if due_date is not None:
        payload["due_date"] = due_date
    if priority is not None:
        payload["priority"] = priority
    if area is not None:
        payload["area"] = AREA_LABELS[area]
    if project_external_ids is not None:
        payload["project_external_ids"] = project_external_ids
    if category is not None:
        payload["categories"] = [category]
    if reason is not None:
        payload["reason"] = reason
    if done_date is not None:
        payload["done_date"] = done_date
    return payload


@tool(
    name="update_task",
    description=(
        "既存タスクを編集する。NotionタスクはSQLiteへ即時反映し、確認済み内容を非同期同期する。"
        "競合中はNotion側の変更内容を確認してから再編集する。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "task_id": {"type": "integer"},
            "external_id": {"type": "string"},
            "title_query": {"type": "string"},
            "title": {"type": "string"},
            "status": {"type": "string"},
            "due_date": {"type": "string"},
            "priority": {"type": "string", "enum": _PRIORITIES},
            "area": {"type": "string", "enum": list(AREAS)},
            "project_id": {"type": "string"},
            "category": {"type": "string", "enum": _CATEGORIES},
            "reason": {"type": "string"},
            "done_date": {"type": "string"},
        },
    },
    requires_confirmation=True,
)
def update_task(
    task_id: int | str | None = None,
    external_id: str | None = None,
    title_query: str | None = None,
    title: str | None = None,
    status: str | None = None,
    due_date: str | None = None,
    priority: str | None = None,
    area: str | None = None,
    project_id: str | None = None,
    category: str | None = None,
    reason: str | None = None,
    done_date: str | None = None,
) -> dict[str, Any]:
    task = _find_task(task_id, external_id, title_query)
    if task is None:
        return {
            "updated": False,
            "error": "対象タスクを1件に絞れませんでした。",
            "candidates": _candidates(title_query),
        }

    normalized_priority = legacy_tasks._normalize_option(priority, _PRIORITIES) if priority else None
    if priority and not normalized_priority:
        return {"updated": False, "error": "priorityはLow/Mid/Highから指定してください。"}
    normalized_area, _ = resolve_area(area, category) if area is not None else (None, "unchanged")
    if area is not None and normalized_area is None:
        return {"updated": False, "error": "areaはpersonal/group/university/workから指定してください。"}
    if title is not None and not str(title).strip():
        return {"updated": False, "error": "タスク名を空にはできません。"}

    project_external_ids: list[str] | None = None
    if project_id is not None:
        if task["source"] == "notion":
            valid, error, project_external_ids = _validate_project(project_id)
        else:
            project_continuity.ensure_project_schema()
            valid = project_continuity.get_project(project_id) is not None
            error = None if valid else "指定されたPETIT内部プロジェクトが見つかりません。"
        if not valid:
            return {"updated": False, "error": error, "project_id": project_id}

    updates: dict[str, Any] = {}
    for key, value in {
        "title": str(title).strip() if title is not None else None,
        "status": status,
        "due_date": due_date,
        "priority": normalized_priority,
        "area": normalized_area,
        "project_id": project_id,
        "category": category,
        "reason": reason,
        "done_date": done_date,
    }.items():
        if value is not None:
            updates[key] = value
    if project_external_ids is not None:
        updates["project_external_id"] = project_external_ids[0] if project_external_ids else None
        updates["project_external_ids"] = json.dumps(project_external_ids, ensure_ascii=False)
    if not updates:
        return {"updated": False, "error": "変更内容がありません。", "task": task}

    base_source_updated_at = task.get("source_updated_at")
    if task.get("sync_status") == "conflict":
        try:
            remote = json.loads(task.get("remote_snapshot_json") or "{}")
        except json.JSONDecodeError:
            remote = {}
        acknowledged_remote_time = remote.get("source_updated_at")
        if acknowledged_remote_time:
            base_source_updated_at = str(acknowledged_remote_time)
            updates["source_updated_at"] = base_source_updated_at
        updates["remote_snapshot_json"] = None
        updates["sync_error"] = None

    now = db.now_iso()
    assignments = [f'"{key}"=?' for key in updates]
    values = list(updates.values())
    assignments.append("updated_at=?")
    values.append(now)
    values.append(int(task["id"]))
    with db.get_connection() as conn:
        conn.execute(f"UPDATE tasks_cache SET {', '.join(assignments)} WHERE id=?", values)

    updated_task = _find_task(int(task["id"])) or {**task, **updates}
    if task["source"] != "notion":
        return {"updated": True, "source": "local", "task": updated_task, "sync_status": "synced"}

    payload = _update_payload(
        title=str(title).strip() if title is not None else None,
        status=status,
        due_date=due_date,
        priority=normalized_priority,
        area=normalized_area,
        project_external_ids=project_external_ids,
        category=category,
        reason=reason,
        done_date=done_date,
    )
    operation_id = task_sync_queue.enqueue_update(
        int(task["id"]),
        payload,
        base_source_updated_at=base_source_updated_at,
    )
    updated_task = _find_task(int(task["id"])) or updated_task
    return {
        "updated": True,
        "source": "notion",
        "queued": True,
        "sync_status": "pending",
        "operation_id": operation_id,
        "task": updated_task,
        "message": "ローカルへ反映し、Notion同期をキューへ追加しました。",
    }


@tool(
    name="complete_task",
    description="タスクを完了にする。Notionタスクはローカルへ即時反映し、非同期で同期する。",
    parameters={
        "type": "object",
        "properties": {
            "task_id": {"type": "integer"},
            "external_id": {"type": "string"},
            "title_query": {"type": "string"},
            "done_date": {"type": "string"},
        },
    },
    requires_confirmation=True,
)
def complete_task(
    task_id: int | str | None = None,
    external_id: str | None = None,
    title_query: str | None = None,
    done_date: str | None = None,
) -> dict[str, Any]:
    result = update_task(
        task_id=task_id,
        external_id=external_id,
        title_query=title_query,
        status=config.NOTION_DONE_STATUS,
        done_date=done_date or date.today().isoformat(),
    )
    if not result.get("updated"):
        return {"completed": False, **result}
    return {"completed": True, **result}


@tool(
    name="retry_task_sync",
    description="failedになったNotionタスク同期を承認後に再試行する。conflictは再試行せず再編集を求める。",
    parameters={
        "type": "object",
        "properties": {"task_id": {"type": "integer"}},
        "required": ["task_id"],
    },
    requires_confirmation=True,
)
def retry_task_sync(task_id: int) -> dict[str, Any]:
    return task_sync_queue.retry_task(int(task_id))


@tool(
    name="get_task_sync_status",
    description="タスクのNotion同期状態、失敗理由、競合時のNotion側スナップショットを確認する。",
    parameters={
        "type": "object",
        "properties": {
            "task_id": {"type": "integer"},
            "limit": {"type": "integer", "default": 20},
        },
    },
)
def get_task_sync_status(task_id: int | None = None, limit: int = 20) -> dict[str, Any]:
    return task_sync_queue.status(task_id=task_id, limit=limit)


def install_agent_routes() -> None:
    """Install Phase 2 routing after backend.agent has finished importing."""
    global _AGENT_ROUTES_INSTALLED
    if _AGENT_ROUTES_INSTALLED:
        return
    from .. import agent  # Imported lazily to avoid the agent -> tools cycle.

    existing = {name for name, _signals in agent._TOOL_SIGNALS}
    additions = []
    if "update_task" not in existing:
        additions.append(
            (
                "update_task",
                (
                    "タスクを編集",
                    "タスクを変更",
                    "タスク名を変更",
                    "期限を変更",
                    "優先度を変更",
                    "未完了に戻",
                ),
            )
        )
    if "retry_task_sync" not in existing:
        additions.append(
            (
                "retry_task_sync",
                ("タスク同期を再試行", "Notion同期を再試行", "同期をやり直"),
            )
        )
    if "get_task_sync_status" not in existing:
        additions.append(
            (
                "get_task_sync_status",
                ("タスク同期状態", "タスクの同期状況", "同期エラー", "同期の失敗理由"),
            )
        )
    agent._TOOL_SIGNALS = tuple(agent._TOOL_SIGNALS) + tuple(additions)
    _AGENT_ROUTES_INSTALLED = True
