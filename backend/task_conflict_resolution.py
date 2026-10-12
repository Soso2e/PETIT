"""Explicit UI conflict choices, guarded by the compared local/remote revision."""
from __future__ import annotations

import hashlib
import json
from typing import Literal

from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import db, notion_client, notifications, task_sync_queue, task_hierarchy


class ConflictChoice(BaseModel):
    choice: Literal["petit", "notion"]
    revision: str = Field(min_length=64, max_length=64)


def _read(conn, task_id):
    row = conn.execute("SELECT * FROM tasks_cache WHERE id=?", (task_id,)).fetchone()
    if not row or row["source"] != "notion" or row["sync_status"] != "conflict":
        raise ValueError("このタスクは同期競合中ではありません。タスクを更新してください。")
    operations = [dict(item) for item in conn.execute(
        "SELECT * FROM task_sync_queue WHERE task_id=? AND status IN ('conflict','failed','pending') ORDER BY id",
        (task_id,),
    ).fetchall()]
    if not operations or any(item["operation"] != "update" for item in operations):
        raise ValueError("比較できる更新履歴がありません。同期状態を確認してください。")
    return dict(row), operations


def _revision(task, operations, remote):
    return hashlib.sha256(json.dumps([task, operations, remote], sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def preview(task_id: int) -> JSONResponse:
    task_hierarchy.ensure_task_hierarchy_schema()
    try:
        with db.get_connection() as conn:
            task, operations = _read(conn, task_id)
        remote = notion_client.get_task_page(task["external_id"])
        fields = ["title", "status", "due_date", "priority", "area", "reason", "done_date"]
        local = {key: task.get(key) for key in fields}
        local["parent_external_ids"] = json.loads(task.get("parent_external_ids") or "[]")
        local["project_external_ids"] = json.loads(task.get("project_external_ids") or "[]")
        with db.get_connection() as conn:
            def parent_titles(ids):
                titles = []
                for external_id in ids:
                    parent = conn.execute("SELECT title FROM tasks_cache WHERE source='notion' AND external_id=?", (external_id,)).fetchone()
                    titles.append(parent["title"] if parent else f"Notionページ ({str(external_id)[:8]})")
                return titles
            parents = {"local": parent_titles(local["parent_external_ids"]), "remote": parent_titles(remote.get("parent_external_ids") or [])}
        return JSONResponse({"task_id": task_id, "local": local,
                             "remote": {key: remote.get(key) for key in local},
                             "parent_titles": parents,
                             "revision": _revision(task, operations, remote)})
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    except notion_client.NotionError:
        return JSONResponse({"error": "Notionを取得できません。対象・親ページの存在、ゴミ箱、連携への共有と接続を確認してください。競合は保持しています。"}, status_code=503)


def list_conflicts() -> dict:
    task_hierarchy.ensure_task_hierarchy_schema()
    with db.get_connection() as conn:
        rows = conn.execute("SELECT id, title, sync_error FROM tasks_cache WHERE sync_status='conflict' ORDER BY id").fetchall()
    return {"tasks": [dict(row) for row in rows]}


def resolve(task_id: int, payload: ConflictChoice) -> JSONResponse:
    task_hierarchy.ensure_task_hierarchy_schema()
    notifications.init_db()
    try:
        with db.get_connection() as conn:
            task, _ = _read(conn, task_id)
        remote = notion_client.get_task_page(task["external_id"])
        now = db.now_iso()
        with db.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            task, operations = _read(conn, task_id)
            if _revision(task, operations, remote) != payload.revision:
                raise ValueError("比較後に内容が変わりました。最新の差分を確認して選び直してください。")
            operation = operations[-1]
            # Keep superseded payloads as evidence; they must never be replayed.
            conn.execute("UPDATE task_sync_queue SET status='superseded', next_attempt_at=NULL, updated_at=? "
                         "WHERE task_id=? AND status IN ('conflict','failed','pending')", (now, task_id))
            if payload.choice == "notion":
                task_sync_queue._apply_remote_result(operation, remote, connection=conn)
                parents = remote.get("parent_external_ids") or []
                parent = conn.execute("SELECT id FROM tasks_cache WHERE source='notion' AND external_id=?",
                                      (parents[0],)).fetchone() if parents else None
                conn.execute("UPDATE tasks_cache SET parent_task_id=? WHERE id=?", (parent["id"] if parent else None, task_id))
                sync_status = "synced"
            else:
                merged = {}
                for item in operations:
                    merged.update(json.loads(item["payload_json"]))
                conn.execute("UPDATE task_sync_queue SET status='pending', payload_json=?, base_source_updated_at=?, "
                             "attempts=0, last_error=NULL, next_attempt_at=?, updated_at=? WHERE id=?",
                             (json.dumps(merged, ensure_ascii=False), remote.get("source_updated_at"), now, now, operation["id"]))
                conn.execute("UPDATE tasks_cache SET source_updated_at=? WHERE id=?", (remote.get("source_updated_at"), task_id))
                task_sync_queue._set_task_sync(conn, task_id, "pending", operation_id=operation["id"], attempts=0, clear_snapshot=True)
                sync_status = "pending"
            conn.execute("INSERT INTO ui_action_audit(action, entity_type, entity_id, payload_json, result_json, created_at) "
                         "VALUES ('resolve_task_conflict','task',?,?,?,?)",
                         (str(task_id), payload.model_dump_json(), json.dumps({"sync_status": sync_status}), now))
        return JSONResponse({"resolved": True, "sync_status": sync_status,
                             "message": "Notion側を採用しました。" if payload.choice == "notion" else "PETIT側の変更を再同期します。まだNotionへの反映は完了していません。"})
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    except notion_client.NotionError:
        return JSONResponse({"error": "Notionを取得できません。接続とページの連携共有を確認してください。競合は保持しています。"}, status_code=503)


notifications.router.add_api_route("/tasks/sync/conflicts", list_conflicts, methods=["GET"])
notifications.router.add_api_route("/tasks/{task_id}/sync/conflict", preview, methods=["GET"])
notifications.router.add_api_route("/tasks/{task_id}/sync/conflict", resolve, methods=["POST"])
