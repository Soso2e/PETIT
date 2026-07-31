"""User-visible notification history and task editing routes.

This module extends the existing notification router without changing the public
Web Push provider boundary. It is installed from ``backend.__init__`` so the
existing ``backend.notifications.router`` remains the single router included by
FastAPI.
"""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import db, notifications

_INSTALLED = False
_ORIGINAL_INIT_DB = notifications.init_db
_ORIGINAL_CREATE_EVENT = notifications._create_event

_EVENT_COLUMNS: dict[str, str] = {
    "read_at": "TEXT",
    "resolved_at": "TEXT",
    "entity_type": "TEXT",
    "entity_id": "TEXT",
    "action_url": "TEXT",
}

_UI_AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS ui_action_audit (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    action       TEXT NOT NULL,
    entity_type  TEXT NOT NULL,
    entity_id    TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    result_json  TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ui_action_audit_entity
ON ui_action_audit(entity_type, entity_id, id);
"""


class NotificationEventUpdate(BaseModel):
    read: bool | None = None
    resolved: bool | None = None


class TaskUiUpdate(BaseModel):
    title: str | None = None
    status: str | None = None
    due_date: str | None = None
    priority: str | None = None
    area: str | None = None
    project_id: str | None = None
    category: str | None = None
    reason: str | None = None
    done_date: str | None = None
    notification_id: int | None = None
    resolve_notification: bool = True


def _model_values(model: BaseModel, *, exclude_none: bool = True) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_none=exclude_none)
    return model.dict(exclude_none=exclude_none)


def _safe_internal_url(value: str | None) -> str:
    url = str(value or "/").strip() or "/"
    if not url.startswith("/") or url.startswith("//"):
        return "/"
    return url[:2048]


def _decorate_target(url: str, event_id: int) -> tuple[str, str | None, str | None]:
    parts = urlsplit(_safe_internal_url(url))
    query = parse_qsl(parts.query, keep_blank_values=True)
    values = {key: value for key, value in query}
    if "notification" not in values:
        query.append(("notification", str(event_id)))

    entity_type = values.get("entity_type") or None
    entity_id = values.get("entity_id") or None
    if values.get("task"):
        entity_type = "task"
        entity_id = values["task"]

    target = urlunsplit((parts.scheme, parts.netloc, parts.path or "/", urlencode(query), parts.fragment))
    return target, entity_type, entity_id


def _ensure_schema() -> None:
    with db.get_connection() as conn:
        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(notification_events)").fetchall()
        }
        for name, declaration in _EVENT_COLUMNS.items():
            if name not in columns:
                conn.execute(f'ALTER TABLE notification_events ADD COLUMN "{name}" {declaration}')
        conn.executescript(_UI_AUDIT_SCHEMA)


def init_db() -> None:
    _ORIGINAL_INIT_DB()
    _ensure_schema()


def _create_event(category: str, title: str, body: str, url: str) -> tuple[int, dict[str, Any]]:
    event_id, payload = _ORIGINAL_CREATE_EVENT(category, title, body, _safe_internal_url(url))
    payload_url = _safe_internal_url(payload.get("url") or url)
    target, entity_type, entity_id = _decorate_target(payload_url, event_id)
    payload.update(
        {
            "event_id": event_id,
            "url": payload_url,
            "entity_type": entity_type,
            "entity_id": entity_id,
        }
    )
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE notification_events SET target_url=?, action_url=?, entity_type=?, entity_id=?, payload_json=? WHERE id=?",
            (
                target,
                target,
                entity_type,
                entity_id,
                json.dumps(payload, ensure_ascii=False),
                event_id,
            ),
        )
    return event_id, payload


def _event_row(row: Any) -> dict[str, Any]:
    item = dict(row)
    try:
        payload = json.loads(item.get("payload_json") or "{}")
    except json.JSONDecodeError:
        payload = {}
    action_url = item.get("action_url") or item.get("target_url") or payload.get("url") or "/"
    entity_type = item.get("entity_type") or payload.get("entity_type")
    entity_id = item.get("entity_id") or payload.get("entity_id")
    if not entity_id:
        _target, inferred_type, inferred_id = _decorate_target(action_url, int(item["id"]))
        entity_type = entity_type or inferred_type
        entity_id = inferred_id
    return {
        "id": int(item["id"]),
        "category": item["category"],
        "title": item["title"],
        "body": item["body"],
        "action_url": action_url,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "created_at": item["created_at"],
        "read_at": item.get("read_at"),
        "resolved_at": item.get("resolved_at"),
        "read": bool(item.get("read_at")),
        "resolved": bool(item.get("resolved_at")),
        "delivery_status": item.get("delivery_status"),
    }


def list_events(*, limit: int = 40, state: str = "open") -> dict[str, Any]:
    init_db()
    normalized = str(state or "open").strip().casefold()
    conditions = {
        "all": "1=1",
        "open": "e.resolved_at IS NULL",
        "unread": "e.read_at IS NULL AND e.resolved_at IS NULL",
        "resolved": "e.resolved_at IS NOT NULL",
    }
    if normalized not in conditions:
        raise ValueError("stateはall/open/unread/resolvedから指定してください。")
    bounded_limit = max(1, min(int(limit), 100))
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT e.*, (SELECT d.status FROM notification_deliveries d "
            "WHERE d.event_id=e.id ORDER BY d.id DESC LIMIT 1) AS delivery_status "
            f"FROM notification_events e WHERE {conditions[normalized]} "
            "ORDER BY e.created_at DESC, e.id DESC LIMIT ?",
            (bounded_limit,),
        ).fetchall()
        unread_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM notification_events WHERE read_at IS NULL AND resolved_at IS NULL"
            ).fetchone()[0]
        )
    return {
        "events": [_event_row(row) for row in rows],
        "unread_count": unread_count,
        "state": normalized,
    }


def update_event_state(
    event_id: int,
    *,
    read: bool | None = None,
    resolved: bool | None = None,
) -> dict[str, Any] | None:
    init_db()
    if read is None and resolved is None:
        raise ValueError("readまたはresolvedを指定してください。")
    now = db.now_iso()
    assignments: list[str] = []
    values: list[Any] = []
    if read is not None:
        assignments.append("read_at=?")
        values.append(now if read else None)
    if resolved is not None:
        assignments.append("resolved_at=?")
        values.append(now if resolved else None)
        if resolved and read is None:
            assignments.append("read_at=COALESCE(read_at, ?)")
            values.append(now)
    values.append(int(event_id))
    with db.get_connection() as conn:
        cursor = conn.execute(
            f"UPDATE notification_events SET {', '.join(assignments)} WHERE id=?",
            values,
        )
        if cursor.rowcount <= 0:
            return None
        row = conn.execute(
            "SELECT e.*, (SELECT d.status FROM notification_deliveries d "
            "WHERE d.event_id=e.id ORDER BY d.id DESC LIMIT 1) AS delivery_status "
            "FROM notification_events e WHERE e.id=?",
            (int(event_id),),
        ).fetchone()
    return _event_row(row)


def _resolve_task_notifications(task_id: int) -> None:
    init_db()
    now = db.now_iso()
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE notification_events SET resolved_at=COALESCE(resolved_at, ?), "
            "read_at=COALESCE(read_at, ?) WHERE entity_type='task' AND entity_id=?",
            (now, now, str(task_id)),
        )


def _task_detail(task_id: int) -> dict[str, Any] | None:
    from . import task_sync_queue

    task_sync_queue.ensure_task_sync_schema()
    with db.get_connection() as conn:
        row = conn.execute("SELECT * FROM tasks_cache WHERE id=?", (int(task_id),)).fetchone()
    return dict(row) if row else None


def _parse_tool_result(raw: str) -> dict[str, Any]:
    if raw.startswith("[error]"):
        return {"error": raw.removeprefix("[error]").strip()}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {"result": raw}
    return value if isinstance(value, dict) else {"result": value}


def _audit(action: str, task_id: int, payload: dict[str, Any], result: dict[str, Any]) -> None:
    init_db()
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO ui_action_audit(action, entity_type, entity_id, payload_json, result_json, created_at) "
            "VALUES (?, 'task', ?, ?, ?, ?)",
            (
                action,
                str(task_id),
                json.dumps(payload, ensure_ascii=False, default=str),
                json.dumps(result, ensure_ascii=False, default=str),
                db.now_iso(),
            ),
        )


def _dispatch_task_action(
    tool_name: str,
    task_id: int,
    values: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    from . import tools

    arguments = {"task_id": int(task_id), **values}
    result = _parse_tool_result(tools.dispatch(tool_name, arguments))
    _audit(tool_name, int(task_id), arguments, result)
    succeeded = bool(result.get("updated") or result.get("completed"))
    if succeeded:
        return result, 200
    if result.get("error") and _task_detail(task_id) is None:
        return result, 404
    return result, 400


def get_notification_events(limit: int = 40, state: str = "open") -> JSONResponse:
    try:
        result = list_events(limit=limit, state=state)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(result)


def patch_notification_event(event_id: int, payload: NotificationEventUpdate) -> JSONResponse:
    values = _model_values(payload)
    try:
        event = update_event_state(
            event_id,
            read=values.get("read"),
            resolved=values.get("resolved"),
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    if event is None:
        return JSONResponse({"error": "通知が見つかりません。"}, status_code=404)
    return JSONResponse({"event": event, "unread_count": list_events(limit=1)["unread_count"]})


def get_notification_task(task_id: int) -> JSONResponse:
    task = _task_detail(task_id)
    if task is None:
        return JSONResponse({"error": "タスクが見つかりません。"}, status_code=404)
    return JSONResponse({"task": task})


def patch_notification_task(task_id: int, payload: TaskUiUpdate) -> JSONResponse:
    values = _model_values(payload)
    notification_id = values.pop("notification_id", None)
    resolve_notification = bool(values.pop("resolve_notification", True))
    if not values:
        return JSONResponse({"error": "変更内容がありません。"}, status_code=400)
    result, status_code = _dispatch_task_action("update_task", task_id, values)
    if status_code == 200 and resolve_notification:
        if notification_id is not None:
            update_event_state(int(notification_id), resolved=True)
        else:
            _resolve_task_notifications(task_id)
    return JSONResponse(result, status_code=status_code)


def complete_notification_task(task_id: int, payload: TaskUiUpdate) -> JSONResponse:
    values = _model_values(payload)
    notification_id = values.pop("notification_id", None)
    resolve_notification = bool(values.pop("resolve_notification", True))
    allowed = {key: value for key, value in values.items() if key == "done_date"}
    result, status_code = _dispatch_task_action("complete_task", task_id, allowed)
    if status_code == 200 and resolve_notification:
        if notification_id is not None:
            update_event_state(int(notification_id), resolved=True)
        else:
            _resolve_task_notifications(task_id)
    return JSONResponse(result, status_code=status_code)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    notifications.init_db = init_db
    notifications._create_event = _create_event
    notifications.router.add_api_route(
        "/events",
        get_notification_events,
        methods=["GET"],
        tags=["notification-center"],
    )
    notifications.router.add_api_route(
        "/events/{event_id}",
        patch_notification_event,
        methods=["PATCH"],
        tags=["notification-center"],
    )
    notifications.router.add_api_route(
        "/tasks/{task_id}",
        get_notification_task,
        methods=["GET"],
        tags=["notification-center"],
    )
    notifications.router.add_api_route(
        "/tasks/{task_id}",
        patch_notification_task,
        methods=["PATCH"],
        tags=["notification-center"],
    )
    notifications.router.add_api_route(
        "/tasks/{task_id}/complete",
        complete_notification_task,
        methods=["POST"],
        tags=["notification-center"],
    )
    _INSTALLED = True
