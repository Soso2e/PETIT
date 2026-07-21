"""Durable Notion task write queue with optimistic local task updates."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from . import db, notion_client, notion_project_sync
from .notion_client import NotionError, create_task_page
from .task_taxonomy import resolve_area

SYNC_STATES = ("pending", "synced", "failed", "conflict")
_MAX_ATTEMPTS = 5
_SYNC_GUARD_INSTALLED = False

_SCHEMA = """
CREATE TABLE IF NOT EXISTS task_sync_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks_cache(id) ON DELETE CASCADE,
    provider TEXT NOT NULL DEFAULT 'notion',
    operation TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    base_source_updated_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    synced_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_task_sync_queue_ready
ON task_sync_queue(status, next_attempt_at, id);
CREATE INDEX IF NOT EXISTS idx_task_sync_queue_task
ON task_sync_queue(task_id, status, id);
"""

_TASK_COLUMNS = {
    "sync_status": "TEXT NOT NULL DEFAULT 'synced'",
    "sync_error": "TEXT",
    "sync_operation_id": "INTEGER",
    "sync_attempts": "INTEGER NOT NULL DEFAULT 0",
    "last_synced_at": "TEXT",
    "remote_snapshot_json": "TEXT",
}


def ensure_task_sync_schema() -> None:
    notion_project_sync.ensure_notion_project_schema()
    with db.get_connection() as conn:
        existing = {str(row["name"]) for row in conn.execute("PRAGMA table_info(tasks_cache)").fetchall()}
        for name, definition in _TASK_COLUMNS.items():
            if name not in existing:
                conn.execute(f'ALTER TABLE tasks_cache ADD COLUMN "{name}" {definition}')
        conn.executescript(_SCHEMA)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_cache_sync_status ON tasks_cache(sync_status, id)")


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def _loads(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _merge_payload(current: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = dict(current)
    for key, value in updates.items():
        if value is not None:
            merged[key] = value
    return merged


def _task(task_id: int) -> dict[str, Any] | None:
    ensure_task_sync_schema()
    with db.get_connection() as conn:
        row = conn.execute("SELECT * FROM tasks_cache WHERE id=?", (int(task_id),)).fetchone()
    return dict(row) if row else None


def _set_task_sync(
    conn: Any,
    task_id: int,
    status: str,
    *,
    operation_id: int | None = None,
    error: str | None = None,
    attempts: int | None = None,
    last_synced_at: str | None = None,
    remote_snapshot_json: str | None = None,
    clear_snapshot: bool = False,
) -> None:
    assignments = ["sync_status=?", "sync_error=?", "updated_at=?"]
    values: list[Any] = [status, error, db.now_iso()]
    if operation_id is not None:
        assignments.append("sync_operation_id=?")
        values.append(operation_id)
    if attempts is not None:
        assignments.append("sync_attempts=?")
        values.append(attempts)
    if last_synced_at is not None:
        assignments.append("last_synced_at=?")
        values.append(last_synced_at)
    if remote_snapshot_json is not None:
        assignments.append("remote_snapshot_json=?")
        values.append(remote_snapshot_json)
    elif clear_snapshot:
        assignments.append("remote_snapshot_json=NULL")
    values.append(task_id)
    conn.execute(f"UPDATE tasks_cache SET {', '.join(assignments)} WHERE id=?", values)


def _active_operation(conn: Any, task_id: int, operation: str) -> Any | None:
    return conn.execute(
        "SELECT * FROM task_sync_queue WHERE task_id=? AND operation=? "
        "AND status IN ('pending','failed') ORDER BY id DESC LIMIT 1",
        (task_id, operation),
    ).fetchone()


def enqueue_create(task_id: int, payload: dict[str, Any]) -> int:
    ensure_task_sync_schema()
    now = db.now_iso()
    with db.get_connection() as conn:
        existing = _active_operation(conn, task_id, "create")
        if existing:
            operation_id = int(existing["id"])
            merged = _merge_payload(_loads(existing["payload_json"]), payload)
            conn.execute(
                "UPDATE task_sync_queue SET payload_json=?, status='pending', attempts=0, next_attempt_at=?, "
                "last_error=NULL, updated_at=? WHERE id=?",
                (_json(merged), now, now, operation_id),
            )
        else:
            cur = conn.execute(
                "INSERT INTO task_sync_queue "
                "(task_id, provider, operation, payload_json, status, attempts, next_attempt_at, created_at, updated_at) "
                "VALUES (?, 'notion', 'create', ?, 'pending', 0, ?, ?, ?)",
                (task_id, _json(payload), now, now, now),
            )
            operation_id = int(cur.lastrowid)
        _set_task_sync(conn, task_id, "pending", operation_id=operation_id, attempts=0, clear_snapshot=True)
    return operation_id


def enqueue_update(
    task_id: int,
    payload: dict[str, Any],
    *,
    base_source_updated_at: str | None,
) -> int:
    ensure_task_sync_schema()
    now = db.now_iso()
    with db.get_connection() as conn:
        task = conn.execute("SELECT external_id FROM tasks_cache WHERE id=?", (task_id,)).fetchone()
        if task is None:
            raise ValueError("対象タスクが見つかりません。")

        if not task["external_id"]:
            create = _active_operation(conn, task_id, "create")
            if create:
                operation_id = int(create["id"])
                merged = _merge_payload(_loads(create["payload_json"]), payload)
                conn.execute(
                    "UPDATE task_sync_queue SET payload_json=?, status='pending', attempts=0, next_attempt_at=?, "
                    "last_error=NULL, updated_at=? WHERE id=?",
                    (_json(merged), now, now, operation_id),
                )
                _set_task_sync(conn, task_id, "pending", operation_id=operation_id, attempts=0, clear_snapshot=True)
                return operation_id

        existing = _active_operation(conn, task_id, "update")
        if existing:
            operation_id = int(existing["id"])
            merged = _merge_payload(_loads(existing["payload_json"]), payload)
            base = existing["base_source_updated_at"] or base_source_updated_at
            conn.execute(
                "UPDATE task_sync_queue SET payload_json=?, base_source_updated_at=?, status='pending', attempts=0, "
                "next_attempt_at=?, last_error=NULL, updated_at=? WHERE id=?",
                (_json(merged), base, now, now, operation_id),
            )
        else:
            cur = conn.execute(
                "INSERT INTO task_sync_queue "
                "(task_id, provider, operation, payload_json, base_source_updated_at, status, attempts, next_attempt_at, created_at, updated_at) "
                "VALUES (?, 'notion', 'update', ?, ?, 'pending', 0, ?, ?, ?)",
                (task_id, _json(payload), base_source_updated_at, now, now, now),
            )
            operation_id = int(cur.lastrowid)
        _set_task_sync(conn, task_id, "pending", operation_id=operation_id, attempts=0, clear_snapshot=True)
    return operation_id


def _claim_next() -> dict[str, Any] | None:
    ensure_task_sync_schema()
    now = db.now_iso()
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM task_sync_queue WHERE status IN ('pending','failed') AND attempts < ? "
            "AND (next_attempt_at IS NULL OR next_attempt_at <= ?) ORDER BY id ASC LIMIT 1",
            (_MAX_ATTEMPTS, now),
        ).fetchone()
        if row is None:
            return None
        attempts = int(row["attempts"] or 0) + 1
        updated = conn.execute(
            "UPDATE task_sync_queue SET status='processing', attempts=?, updated_at=? "
            "WHERE id=? AND status IN ('pending','failed')",
            (attempts, now, row["id"]),
        ).rowcount
        if not updated:
            return None
        claimed = dict(row)
        claimed["attempts"] = attempts
        claimed["status"] = "processing"
        _set_task_sync(conn, int(row["task_id"]), "pending", operation_id=int(row["id"]), attempts=attempts)
        return claimed


def _retry_at(attempts: int) -> str:
    seconds = min(1800, 30 * (2 ** max(0, attempts - 1)))
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="seconds")


def _mark_failed(operation: dict[str, Any], exc: Exception) -> None:
    error = str(exc)[:500] or type(exc).__name__
    attempts = int(operation.get("attempts") or 1)
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE task_sync_queue SET status='failed', next_attempt_at=?, last_error=?, updated_at=? WHERE id=?",
            (_retry_at(attempts), error, db.now_iso(), operation["id"]),
        )
        _set_task_sync(
            conn,
            int(operation["task_id"]),
            "failed",
            operation_id=int(operation["id"]),
            error=error,
            attempts=attempts,
        )


def _mark_conflict(operation: dict[str, Any], task: dict[str, Any], message: str) -> None:
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE task_sync_queue SET status='conflict', last_error=?, next_attempt_at=NULL, updated_at=? WHERE id=?",
            (message, db.now_iso(), operation["id"]),
        )
        _set_task_sync(
            conn,
            int(task["id"]),
            "conflict",
            operation_id=int(operation["id"]),
            error=message,
            attempts=int(operation.get("attempts") or 0),
        )


def _apply_remote_result(operation: dict[str, Any], remote: dict[str, Any]) -> None:
    task_id = int(operation["task_id"])
    now = db.now_iso()
    area, _ = resolve_area(remote.get("area"), remote.get("category"))
    project_external_ids = [str(item) for item in remote.get("project_external_ids") or [] if str(item).strip()]
    parent_external_ids = [str(item) for item in remote.get("parent_external_ids") or [] if str(item).strip()]
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE tasks_cache SET source='notion', title=?, status=?, due_date=?, priority=?, category=?, area=?, reason=?, "
            "external_id=?, url=?, done_date=?, project_external_id=?, project_external_ids=?, assignee_external_ids=?, "
            "parent_external_id=?, parent_external_ids=?, subtask_external_ids=?, summary=?, source_updated_at=?, "
            "sync_status='synced', sync_error=NULL, sync_operation_id=?, sync_attempts=?, last_synced_at=?, "
            "remote_snapshot_json=NULL, updated_at=? WHERE id=?",
            (
                remote.get("title") or "タイトルなし",
                remote.get("status") or "unknown",
                remote.get("due_date"),
                remote.get("priority"),
                remote.get("category"),
                area,
                remote.get("reason"),
                remote.get("external_id"),
                remote.get("url"),
                remote.get("done_date"),
                project_external_ids[0] if project_external_ids else None,
                json.dumps(project_external_ids, ensure_ascii=False),
                json.dumps(remote.get("assignee_external_ids") or [], ensure_ascii=False),
                parent_external_ids[0] if parent_external_ids else None,
                json.dumps(parent_external_ids, ensure_ascii=False),
                json.dumps(remote.get("subtask_external_ids") or [], ensure_ascii=False),
                remote.get("summary"),
                remote.get("source_updated_at"),
                int(operation["id"]),
                int(operation.get("attempts") or 0),
                now,
                now,
                task_id,
            ),
        )
        conn.execute(
            "UPDATE task_sync_queue SET status='synced', last_error=NULL, next_attempt_at=NULL, synced_at=?, updated_at=? WHERE id=?",
            (now, now, operation["id"]),
        )


def _update_remote_task(page_id: str, payload: dict[str, Any]) -> dict[str, Any]:
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
    if not props:
        raise NotionError("更新するNotionプロパティがありません。")
    return notion_client.parse_task_page(
        notion_client._patch(f"/pages/{page_id}", {"properties": props}, timeout=20)
    )


def _execute(operation: dict[str, Any]) -> None:
    task = _task(int(operation["task_id"]))
    if task is None:
        raise ValueError("同期対象タスクが見つかりません。")
    payload = _loads(operation.get("payload_json"))

    if operation["operation"] == "create":
        remote = create_task_page(**payload)
        _apply_remote_result(operation, remote)
        return
    if operation["operation"] != "update":
        raise ValueError(f"未対応のタスク同期操作です: {operation['operation']}")
    if task.get("sync_status") == "conflict":
        _mark_conflict(operation, task, task.get("sync_error") or "Notion側の更新と競合しています。")
        return

    base = operation.get("base_source_updated_at")
    current = task.get("source_updated_at")
    if base and current and str(base) != str(current):
        _mark_conflict(operation, task, "Notion側がローカル編集後に更新されたため、自動上書きを停止しました。")
        return
    external_id = str(task.get("external_id") or "").strip()
    if not external_id:
        raise NotionError("Notionページ作成が未完了のため、更新を後で再試行します。")
    _apply_remote_result(operation, _update_remote_task(external_id, payload))


def process_next() -> bool:
    operation = _claim_next()
    if operation is None:
        return False
    try:
        _execute(operation)
    except Exception as exc:  # noqa: BLE001 - queue retains failure details
        _mark_failed(operation, exc)
    return True


def retry_task(task_id: int) -> dict[str, Any]:
    ensure_task_sync_schema()
    now = db.now_iso()
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM task_sync_queue WHERE task_id=? AND status IN ('failed','conflict') ORDER BY id DESC LIMIT 1",
            (int(task_id),),
        ).fetchone()
        if row is None:
            return {"queued": False, "error": "再試行できる同期エラーがありません。", "task_id": int(task_id)}
        if row["status"] == "conflict":
            return {
                "queued": False,
                "conflict": True,
                "error": "Notion側の変更と競合しています。同期状態を確認してから編集し直してください。",
                "task_id": int(task_id),
                "operation_id": int(row["id"]),
            }
        conn.execute(
            "UPDATE task_sync_queue SET status='pending', attempts=0, next_attempt_at=?, last_error=NULL, updated_at=? WHERE id=?",
            (now, now, row["id"]),
        )
        _set_task_sync(conn, int(task_id), "pending", operation_id=int(row["id"]), attempts=0)
    return {"queued": True, "task_id": int(task_id), "operation_id": int(row["id"]), "sync_status": "pending"}


def status(*, task_id: int | None = None, limit: int = 20) -> dict[str, Any]:
    ensure_task_sync_schema()
    limit = max(1, min(int(limit), 100))
    with db.get_connection() as conn:
        counts = {
            str(row["status"]): int(row["count"])
            for row in conn.execute("SELECT status, COUNT(*) AS count FROM task_sync_queue GROUP BY status").fetchall()
        }
        if task_id is None:
            rows = conn.execute(
                "SELECT id, task_id, operation, status, attempts, next_attempt_at, last_error, created_at, updated_at, synced_at "
                "FROM task_sync_queue ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            task_data = None
        else:
            rows = conn.execute(
                "SELECT id, task_id, operation, status, attempts, next_attempt_at, last_error, created_at, updated_at, synced_at "
                "FROM task_sync_queue WHERE task_id=? ORDER BY id DESC LIMIT ?",
                (int(task_id), limit),
            ).fetchall()
            task_row = conn.execute(
                "SELECT id, source, external_id, title, status, due_date, priority, area, project_id, "
                "sync_status, sync_error, sync_attempts, last_synced_at, source_updated_at, remote_snapshot_json "
                "FROM tasks_cache WHERE id=?",
                (int(task_id),),
            ).fetchone()
            task_data = dict(task_row) if task_row else None
    if task_data and task_data.get("remote_snapshot_json"):
        task_data["remote_snapshot"] = _loads(task_data.pop("remote_snapshot_json"))
    elif task_data:
        task_data.pop("remote_snapshot_json", None)
    return {"counts": counts, "operations": [dict(row) for row in rows], "task_id": task_id, "task": task_data}


def upsert_tasks_with_conflict_guard(tasks: list[dict[str, Any]]) -> int:
    """Merge Notion reads without overwriting approved local pending edits."""
    ensure_task_sync_schema()
    now = db.now_iso()
    seen_ids: list[str] = []
    with db.get_connection() as conn:
        for task in tasks:
            external_id = str(task.get("external_id") or "").strip()
            title = str(task.get("title") or "").strip()
            if not external_id or not title:
                continue
            seen_ids.append(external_id)
            project_external_ids = [str(item) for item in task.get("project_external_ids") or [] if str(item).strip()]
            parent_external_ids = [str(item) for item in task.get("parent_external_ids") or [] if str(item).strip()]
            project_id = notion_project_sync._resolve_task_project(conn, project_external_ids)
            existing = conn.execute(
                "SELECT * FROM tasks_cache WHERE source='notion' AND external_id=?",
                (external_id,),
            ).fetchone()

            if existing and str(existing["sync_status"] or "synced") in {"pending", "failed", "conflict"}:
                previous_remote_time = existing["source_updated_at"]
                incoming_remote_time = task.get("source_updated_at")
                if previous_remote_time and incoming_remote_time and str(previous_remote_time) != str(incoming_remote_time):
                    message = "Notion側にも更新があるため、ローカル編集の自動上書きを停止しました。"
                    conn.execute(
                        "UPDATE tasks_cache SET sync_status='conflict', sync_error=?, remote_snapshot_json=?, updated_at=? WHERE id=?",
                        (message, _json(task), now, existing["id"]),
                    )
                    conn.execute(
                        "UPDATE task_sync_queue SET status='conflict', last_error=?, next_attempt_at=NULL, updated_at=? "
                        "WHERE task_id=? AND status IN ('pending','failed','processing')",
                        (message, now, existing["id"]),
                    )
                continue

            area, _ = resolve_area(task.get("area"), task.get("category"))
            values = (
                title,
                task.get("status") or "unknown",
                task.get("due_date"),
                task.get("priority"),
                task.get("category"),
                area,
                task.get("reason"),
                task.get("url"),
                task.get("done_date"),
                project_external_ids[0] if project_external_ids else None,
                json.dumps(project_external_ids, ensure_ascii=False),
                project_id,
                json.dumps(task.get("assignee_external_ids") or [], ensure_ascii=False),
                parent_external_ids[0] if parent_external_ids else None,
                json.dumps(parent_external_ids, ensure_ascii=False),
                json.dumps(task.get("subtask_external_ids") or [], ensure_ascii=False),
                task.get("summary"),
                task.get("source_updated_at"),
                now,
                now,
                external_id,
            )
            if existing:
                conn.execute(
                    "UPDATE tasks_cache SET title=?, status=?, due_date=?, priority=?, category=?, area=?, reason=?, url=?, done_date=?, "
                    "project_external_id=?, project_external_ids=?, project_id=?, assignee_external_ids=?, parent_external_id=?, "
                    "parent_external_ids=?, subtask_external_ids=?, summary=?, source_updated_at=?, updated_at=?, "
                    "sync_status='synced', sync_error=NULL, last_synced_at=?, remote_snapshot_json=NULL "
                    "WHERE source='notion' AND external_id=?",
                    values,
                )
            else:
                conn.execute(
                    "INSERT INTO tasks_cache "
                    "(source, title, status, due_date, priority, category, area, reason, url, done_date, project_external_id, "
                    "project_external_ids, project_id, assignee_external_ids, parent_external_id, parent_external_ids, "
                    "subtask_external_ids, summary, source_updated_at, updated_at, last_synced_at, external_id, sync_status) "
                    "VALUES ('notion', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'synced')",
                    values,
                )

        if seen_ids:
            placeholders = ",".join("?" for _ in seen_ids)
            conn.execute(
                "DELETE FROM tasks_cache WHERE source='notion' AND sync_status='synced' "
                f"AND (external_id IS NULL OR external_id NOT IN ({placeholders}))",
                seen_ids,
            )
        else:
            conn.execute("DELETE FROM tasks_cache WHERE source='notion' AND sync_status='synced'")
    return len(seen_ids)


def install_sync_guard() -> None:
    global _SYNC_GUARD_INSTALLED
    if _SYNC_GUARD_INSTALLED:
        return
    notion_project_sync.upsert_tasks = upsert_tasks_with_conflict_guard
    _SYNC_GUARD_INSTALLED = True
