"""Three-way merge between Notion snapshots and PETIT optimistic state."""
from __future__ import annotations

import json
from typing import Any

from .. import db, notion_project_sync
from ..task_taxonomy import resolve_area
from . import store

REMOTE_FIELDS = (
    "title",
    "status",
    "due_date",
    "priority",
    "category",
    "area",
    "reason",
    "done_date",
    "project_external_ids",
    "assignee_external_ids",
    "parent_external_ids",
    "subtask_external_ids",
    "summary",
)


def _list(value: Any) -> list[str]:
    if isinstance(value, str):
        parsed = store.json_loads(value, [])
        value = parsed if isinstance(parsed, list) else []
    return [str(item) for item in (value or []) if str(item).strip()]


def _remote_fields(task: dict[str, Any]) -> dict[str, Any]:
    area, _ = resolve_area(task.get("area"), task.get("category"))
    return {
        "title": str(task.get("title") or ""),
        "status": str(task.get("status") or "unknown"),
        "due_date": task.get("due_date"),
        "priority": task.get("priority"),
        "category": task.get("category"),
        "area": area,
        "reason": task.get("reason"),
        "done_date": task.get("done_date"),
        "project_external_ids": _list(task.get("project_external_ids")),
        "assignee_external_ids": _list(task.get("assignee_external_ids")),
        "parent_external_ids": _list(task.get("parent_external_ids")),
        "subtask_external_ids": _list(task.get("subtask_external_ids")),
        "summary": task.get("summary"),
    }


def _local_fields(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": str(task.get("title") or ""),
        "status": str(task.get("status") or "unknown"),
        "due_date": task.get("due_date"),
        "priority": task.get("priority"),
        "category": task.get("category"),
        "area": task.get("area"),
        "reason": task.get("reason"),
        "done_date": task.get("done_date"),
        "project_external_ids": _list(task.get("project_external_ids")),
        "assignee_external_ids": _list(task.get("assignee_external_ids")),
        "parent_external_ids": _list(task.get("parent_external_ids")),
        "subtask_external_ids": _list(task.get("subtask_external_ids")),
        "summary": task.get("summary"),
    }


def _snapshot(conn: Any, external_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT payload_json FROM notion_task_remote_snapshots WHERE external_id=?",
        (external_id,),
    ).fetchone()
    if not row:
        return None
    value = store.json_loads(row["payload_json"], {})
    return value if isinstance(value, dict) else None


def save_snapshot(remote: dict[str, Any]) -> None:
    store.ensure_schema()
    with db.get_connection() as conn:
        _save_snapshot(conn, remote)


def _save_snapshot(conn: Any, task: dict[str, Any]) -> None:
    external_id = str(task.get("external_id") or "").strip()
    if not external_id:
        return
    conn.execute(
        "INSERT INTO notion_task_remote_snapshots(external_id, payload_json, source_updated_at, archived, received_at) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT(external_id) DO UPDATE SET "
        "payload_json=excluded.payload_json, source_updated_at=excluded.source_updated_at, "
        "archived=excluded.archived, received_at=excluded.received_at",
        (
            external_id,
            store.json_dumps(task),
            task.get("source_updated_at"),
            int(bool(task.get("archived"))),
            db.now_iso(),
        ),
    )


def _db_values(conn: Any, remote: dict[str, Any]) -> dict[str, Any]:
    fields = _remote_fields(remote)
    project_ids = fields["project_external_ids"]
    parent_ids = fields["parent_external_ids"]
    return {
        "title": fields["title"] or "タイトルなし",
        "status": fields["status"],
        "due_date": fields["due_date"],
        "priority": fields["priority"],
        "category": fields["category"],
        "area": fields["area"],
        "reason": fields["reason"],
        "url": remote.get("url"),
        "done_date": fields["done_date"],
        "project_external_id": project_ids[0] if project_ids else None,
        "project_external_ids": json.dumps(project_ids, ensure_ascii=False),
        "project_id": notion_project_sync._resolve_task_project(conn, project_ids),
        "assignee_external_ids": json.dumps(fields["assignee_external_ids"], ensure_ascii=False),
        "parent_external_id": parent_ids[0] if parent_ids else None,
        "parent_external_ids": json.dumps(parent_ids, ensure_ascii=False),
        "subtask_external_ids": json.dumps(fields["subtask_external_ids"], ensure_ascii=False),
        "summary": fields["summary"],
        "source_updated_at": remote.get("source_updated_at"),
    }


def _insert_remote(conn: Any, remote: dict[str, Any]) -> int:
    values = _db_values(conn, remote)
    now = db.now_iso()
    cur = conn.execute(
        "INSERT INTO tasks_cache "
        "(source, title, status, due_date, priority, category, area, reason, url, done_date, "
        "project_external_id, project_external_ids, project_id, assignee_external_ids, "
        "parent_external_id, parent_external_ids, subtask_external_ids, summary, source_updated_at, "
        "updated_at, last_synced_at, external_id, sync_status, remote_deleted_at) "
        "VALUES ('notion', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'synced', NULL)",
        (
            values["title"], values["status"], values["due_date"], values["priority"],
            values["category"], values["area"], values["reason"], values["url"],
            values["done_date"], values["project_external_id"], values["project_external_ids"],
            values["project_id"], values["assignee_external_ids"], values["parent_external_id"],
            values["parent_external_ids"], values["subtask_external_ids"], values["summary"],
            values["source_updated_at"], now, now, remote["external_id"],
        ),
    )
    return int(cur.lastrowid)


def _apply_remote_columns(
    conn: Any,
    task_id: int,
    remote: dict[str, Any],
    *,
    fields: set[str] | None = None,
    keep_sync_status: bool = False,
) -> None:
    values = _db_values(conn, remote)
    selected = set(REMOTE_FIELDS) if fields is None else set(fields)
    column_map = {
        "title": ("title",), "status": ("status",), "due_date": ("due_date",),
        "priority": ("priority",), "category": ("category",), "area": ("area",),
        "reason": ("reason",), "done_date": ("done_date",),
        "project_external_ids": ("project_external_id", "project_external_ids", "project_id"),
        "assignee_external_ids": ("assignee_external_ids",),
        "parent_external_ids": ("parent_external_id", "parent_external_ids"),
        "subtask_external_ids": ("subtask_external_ids",), "summary": ("summary",),
    }
    columns: list[str] = []
    params: list[Any] = []
    for field in REMOTE_FIELDS:
        if field not in selected:
            continue
        for column in column_map[field]:
            columns.append(f"{column}=?")
            params.append(values[column])
    now = db.now_iso()
    columns.extend([
        "source='notion'", "url=?", "source_updated_at=?", "last_synced_at=?",
        "remote_deleted_at=NULL", "updated_at=?",
    ])
    params.extend([values["url"], values["source_updated_at"], now, now])
    if not keep_sync_status:
        columns.extend(["sync_status='synced'", "sync_error=NULL", "remote_snapshot_json=NULL"])
    params.append(task_id)
    conn.execute(f"UPDATE tasks_cache SET {', '.join(columns)} WHERE id=?", params)


def _mark_conflict(conn: Any, local: dict[str, Any], remote: dict[str, Any], fields: list[str]) -> None:
    message = "PETITとNotionの両方で同じ項目が更新されています: " + ", ".join(fields)
    now = db.now_iso()
    conn.execute(
        "UPDATE tasks_cache SET sync_status='conflict', sync_error=?, remote_snapshot_json=?, updated_at=? WHERE id=?",
        (message, store.json_dumps(remote), now, local["id"]),
    )
    conn.execute(
        "UPDATE task_sync_queue SET status='conflict', last_error=?, next_attempt_at=NULL, updated_at=? "
        "WHERE task_id=? AND status IN ('pending','failed','processing')",
        (message, now, local["id"]),
    )


def mark_remote_deleted(external_id: str, deleted_at: str | None = None) -> str:
    store.ensure_schema()
    with db.get_connection() as conn:
        row = conn.execute("SELECT * FROM tasks_cache WHERE external_id=?", (external_id,)).fetchone()
        if not row:
            return "missing"
        local = dict(row)
        deleted_time = store.parse_time(deleted_at)
        current_time = store.parse_time(local.get("source_updated_at"))
        if deleted_time and current_time and deleted_time <= current_time:
            return "stale_delete_ignored"
        if str(local.get("sync_status") or "synced") in {"pending", "failed", "conflict"}:
            remote = {"external_id": external_id, "archived": True, "source_updated_at": deleted_at or db.now_iso()}
            _mark_conflict(conn, local, remote, ["deleted"])
            _save_snapshot(conn, remote)
            return "conflict"
        now = db.now_iso()
        conn.execute(
            "UPDATE tasks_cache SET remote_deleted_at=?, last_synced_at=?, updated_at=?, "
            "sync_status='synced', sync_error=NULL WHERE id=?",
            (deleted_at or now, now, now, local["id"]),
        )
        _save_snapshot(conn, {"external_id": external_id, "archived": True, "source_updated_at": deleted_at or now})
        return "deleted"


def merge_remote_task(remote: dict[str, Any]) -> str:
    """Three-way merge one Notion task into the local materialized view."""
    store.ensure_schema()
    external_id = str(remote.get("external_id") or "").strip()
    if not external_id:
        return "ignored"
    if remote.get("archived"):
        return mark_remote_deleted(external_id, remote.get("source_updated_at"))

    with db.get_connection() as conn:
        row = conn.execute("SELECT * FROM tasks_cache WHERE external_id=?", (external_id,)).fetchone()
        if row is None:
            _insert_remote(conn, remote)
            _save_snapshot(conn, remote)
            return "inserted"

        local = dict(row)
        sync_status = str(local.get("sync_status") or "synced")
        base = _snapshot(conn, external_id)
        if sync_status not in {"pending", "failed", "conflict"}:
            _apply_remote_columns(conn, int(local["id"]), remote)
            _save_snapshot(conn, remote)
            return "updated"

        if sync_status == "conflict":
            conn.execute(
                "UPDATE tasks_cache SET remote_snapshot_json=?, source_updated_at=?, updated_at=? WHERE id=?",
                (store.json_dumps(remote), remote.get("source_updated_at"), db.now_iso(), local["id"]),
            )
            _save_snapshot(conn, remote)
            return "conflict_refreshed"

        if base is None:
            previous_time = str(local.get("source_updated_at") or "")
            incoming_time = str(remote.get("source_updated_at") or "")
            if _local_fields(local) == _remote_fields(remote):
                now = db.now_iso()
                conn.execute(
                    "UPDATE tasks_cache SET source_updated_at=?, last_synced_at=?, updated_at=? WHERE id=?",
                    (remote.get("source_updated_at"), now, now, local["id"]),
                )
                conn.execute(
                    "UPDATE task_sync_queue SET base_source_updated_at=?, updated_at=? "
                    "WHERE task_id=? AND status IN ('pending','failed','processing')",
                    (remote.get("source_updated_at"), now, local["id"]),
                )
                _save_snapshot(conn, remote)
                return "local_pending_kept"
            if previous_time and previous_time == incoming_time:
                _save_snapshot(conn, remote)
                return "local_pending_kept"
            _mark_conflict(conn, local, remote, ["unknown_base"])
            _save_snapshot(conn, remote)
            return "conflict"

        base_fields = _remote_fields(base)
        local_fields = _local_fields(local)
        remote_fields = _remote_fields(remote)
        local_changed = {field for field in REMOTE_FIELDS if local_fields[field] != base_fields[field]}
        remote_changed = {field for field in REMOTE_FIELDS if remote_fields[field] != base_fields[field]}
        conflicts = sorted(
            field for field in local_changed & remote_changed if local_fields[field] != remote_fields[field]
        )
        if conflicts:
            _mark_conflict(conn, local, remote, conflicts)
            _save_snapshot(conn, remote)
            return "conflict"

        remote_only = remote_changed - local_changed
        if remote_only:
            _apply_remote_columns(conn, int(local["id"]), remote, fields=remote_only, keep_sync_status=True)
        else:
            now = db.now_iso()
            conn.execute(
                "UPDATE tasks_cache SET source_updated_at=?, last_synced_at=?, updated_at=? WHERE id=?",
                (remote.get("source_updated_at"), now, now, local["id"]),
            )
        conn.execute(
            "UPDATE task_sync_queue SET base_source_updated_at=?, updated_at=? "
            "WHERE task_id=? AND status IN ('pending','failed','processing')",
            (remote.get("source_updated_at"), db.now_iso(), local["id"]),
        )
        _save_snapshot(conn, remote)
        return "merged" if remote_only else "local_pending_kept"


def mark_missing_after_full(seen_ids: set[str], deleted_at: str) -> int:
    store.ensure_schema()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT id, external_id, sync_status FROM tasks_cache "
            "WHERE source='notion' AND remote_deleted_at IS NULL"
        ).fetchall()
        count = 0
        for row in rows:
            external_id = str(row["external_id"] or "")
            if external_id and external_id in seen_ids:
                continue
            if str(row["sync_status"] or "synced") in {"pending", "failed", "conflict"}:
                continue
            conn.execute(
                "UPDATE tasks_cache SET remote_deleted_at=?, last_synced_at=?, updated_at=? WHERE id=?",
                (deleted_at, deleted_at, deleted_at, row["id"]),
            )
            count += 1
    return count
