"""Persistent one-shot reminders backed by SQLite and PETIT Web Push.

The module attaches reminder routes below ``/api/notifications/reminders`` so it
can reuse the existing notification router without changing the FastAPI app
wiring. It also wraps ``notifications.init_db`` so the reminder scheduler is
started from PETIT's existing startup hook.
"""
from __future__ import annotations

import atexit
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import config, db, notifications

_REMINDER_SCHEMA = """
CREATE TABLE IF NOT EXISTS reminders (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id          TEXT NOT NULL,
    title             TEXT NOT NULL,
    message           TEXT NOT NULL,
    trigger_at        TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'scheduled',
    target_url        TEXT NOT NULL DEFAULT '/static/universe.html?view=reminders',
    related_task_id   INTEGER,
    source_message    TEXT,
    delivery_status   TEXT,
    delivery_event_id INTEGER,
    snooze_count      INTEGER NOT NULL DEFAULT 0,
    last_error        TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    fired_at          TEXT,
    completed_at      TEXT,
    cancelled_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_reminders_due
ON reminders(owner_id, status, trigger_at, id);

CREATE INDEX IF NOT EXISTS idx_reminders_updated
ON reminders(owner_id, updated_at, id);
"""

_ACTIVE_STATUSES = ("scheduled", "snoozed", "dispatching", "fired", "failed")
_HISTORY_STATUSES = ("completed", "cancelled")
_INSTALLED = False
_ORIGINAL_NOTIFICATION_INIT_DB = notifications.init_db
_ORIGINAL_NOTIFICATION_STATUS = notifications.notification_status


class ReminderCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    trigger_at: str | None = Field(default=None, max_length=80)
    delay_minutes: int | None = Field(default=None, ge=1, le=525_600)
    message: str | None = Field(default=None, max_length=500)
    target_url: str = Field(default="/static/universe.html?view=reminders", min_length=1, max_length=2048)
    related_task_id: int | None = None
    source_message: str | None = Field(default=None, max_length=2000)


class ReminderSnoozeRequest(BaseModel):
    minutes: int = Field(default=10, ge=1, le=10_080)


def _owner_id() -> str:
    return str(getattr(config, "PETIT_OWNER_ID", "soso") or "soso")


def _timezone_name() -> str:
    return os.getenv("PETIT_TIMEZONE", "Asia/Tokyo").strip() or "Asia/Tokyo"


def _local_zone() -> ZoneInfo:
    try:
        return ZoneInfo(_timezone_name())
    except ZoneInfoNotFoundError:
        return ZoneInfo("Asia/Tokyo")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse_trigger(value: str) -> datetime:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("trigger_at is required when delay_minutes is not supplied")
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("trigger_at must be an ISO date-time such as 2026-08-03T14:00:00+09:00") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_local_zone())
    return parsed.astimezone(timezone.utc)


def ensure_schema(*, recover_dispatching: bool = False) -> None:
    with db.get_connection() as conn:
        conn.executescript(_REMINDER_SCHEMA)
        if recover_dispatching:
            conn.execute(
                "UPDATE reminders SET status='scheduled', updated_at=? WHERE status='dispatching'",
                (db.now_iso(),),
            )


def _serialize(row: Any) -> dict[str, Any]:
    item = dict(row)
    item["snooze_count"] = int(item.get("snooze_count") or 0)
    return item


def get_reminder(reminder_id: int) -> dict[str, Any] | None:
    ensure_schema()
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM reminders WHERE id=? AND owner_id=?",
            (int(reminder_id), _owner_id()),
        ).fetchone()
    return _serialize(row) if row else None


def create_reminder(
    *,
    title: str,
    trigger_at: str | None = None,
    delay_minutes: int | None = None,
    message: str | None = None,
    target_url: str = "/static/universe.html?view=reminders",
    related_task_id: int | None = None,
    source_message: str | None = None,
) -> dict[str, Any]:
    normalized_title = str(title or "").strip()
    if not normalized_title:
        raise ValueError("title is required")
    if delay_minutes is not None and trigger_at:
        raise ValueError("Specify either trigger_at or delay_minutes, not both")
    if delay_minutes is not None:
        if int(delay_minutes) < 1:
            raise ValueError("delay_minutes must be at least 1")
        trigger = _utc_now() + timedelta(minutes=int(delay_minutes))
    else:
        trigger = _parse_trigger(str(trigger_at or ""))
    if trigger <= _utc_now() - timedelta(seconds=5):
        raise ValueError("Reminder time must be in the future")

    ensure_schema()
    now = db.now_iso()
    normalized_message = str(message or "").strip() or f"{normalized_title}の時間だよ。"
    normalized_url = str(target_url or "").strip() or "/static/universe.html?view=reminders"
    with db.get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO reminders(owner_id, title, message, trigger_at, status, target_url, related_task_id, "
            "source_message, created_at, updated_at) VALUES (?, ?, ?, ?, 'scheduled', ?, ?, ?, ?, ?)",
            (
                _owner_id(),
                normalized_title[:160],
                normalized_message[:500],
                _iso_utc(trigger),
                normalized_url[:2048],
                related_task_id,
                (str(source_message or "").strip()[:2000] or None),
                now,
                now,
            ),
        )
        reminder_id = int(cur.lastrowid)
    item = get_reminder(reminder_id)
    if item is None:  # pragma: no cover - defensive
        raise RuntimeError("Reminder was created but could not be loaded")
    return item


def list_reminders(*, scope: str = "upcoming", status: str | None = None, limit: int = 200) -> dict[str, Any]:
    ensure_schema()
    normalized_scope = str(scope or "upcoming").strip().casefold()
    bounded_limit = max(1, min(int(limit), 500))
    where = ["owner_id=?"]
    params: list[Any] = [_owner_id()]

    if status:
        where.append("status=?")
        params.append(str(status).strip().casefold())
    elif normalized_scope == "upcoming":
        placeholders = ",".join("?" for _ in _ACTIVE_STATUSES)
        where.append(f"status IN ({placeholders})")
        params.extend(_ACTIVE_STATUSES)
    elif normalized_scope == "history":
        placeholders = ",".join("?" for _ in _HISTORY_STATUSES)
        where.append(f"status IN ({placeholders})")
        params.extend(_HISTORY_STATUSES)
    elif normalized_scope != "all":
        raise ValueError("scope must be upcoming, history, or all")

    order_sql = (
        "CASE WHEN status IN ('scheduled','snoozed','dispatching') THEN 0 "
        "WHEN status IN ('fired','failed') THEN 1 ELSE 2 END, "
        "CASE WHEN status IN ('scheduled','snoozed','dispatching') THEN trigger_at END ASC, "
        "updated_at DESC, id DESC"
    )
    params.append(bounded_limit)
    with db.get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM reminders WHERE {' AND '.join(where)} ORDER BY {order_sql} LIMIT ?",
            tuple(params),
        ).fetchall()
        count_rows = conn.execute(
            "SELECT status, COUNT(*) AS count FROM reminders WHERE owner_id=? GROUP BY status",
            (_owner_id(),),
        ).fetchall()
    counts = {str(row["status"]): int(row["count"]) for row in count_rows}
    return {
        "scope": normalized_scope,
        "count": len(rows),
        "items": [_serialize(row) for row in rows],
        "counts": counts,
        "timezone": _timezone_name(),
    }


def _set_terminal_status(reminder_id: int, status: str) -> dict[str, Any]:
    if status not in {"completed", "cancelled"}:
        raise ValueError("Unsupported terminal status")
    ensure_schema()
    now = db.now_iso()
    timestamp_column = "completed_at" if status == "completed" else "cancelled_at"
    with db.get_connection() as conn:
        cur = conn.execute(
            f"UPDATE reminders SET status=?, {timestamp_column}=?, updated_at=? "
            "WHERE id=? AND owner_id=? AND status NOT IN ('completed','cancelled')",
            (status, now, now, int(reminder_id), _owner_id()),
        )
    item = get_reminder(reminder_id)
    if item is None:
        raise ValueError("Reminder not found")
    return {"updated": cur.rowcount > 0, "reminder": item}


def complete_reminder(reminder_id: int) -> dict[str, Any]:
    return _set_terminal_status(reminder_id, "completed")


def cancel_reminder(reminder_id: int) -> dict[str, Any]:
    return _set_terminal_status(reminder_id, "cancelled")


def snooze_reminder(reminder_id: int, minutes: int = 10) -> dict[str, Any]:
    bounded_minutes = max(1, min(int(minutes), 10_080))
    ensure_schema()
    now = db.now_iso()
    next_trigger = _iso_utc(_utc_now() + timedelta(minutes=bounded_minutes))
    with db.get_connection() as conn:
        cur = conn.execute(
            "UPDATE reminders SET trigger_at=?, status='snoozed', snooze_count=snooze_count+1, "
            "delivery_status=NULL, delivery_event_id=NULL, last_error=NULL, fired_at=NULL, updated_at=? "
            "WHERE id=? AND owner_id=? AND status NOT IN ('completed','cancelled')",
            (next_trigger, now, int(reminder_id), _owner_id()),
        )
    item = get_reminder(reminder_id)
    if item is None:
        raise ValueError("Reminder not found")
    return {"updated": cur.rowcount > 0, "reminder": item}


def process_due_reminders(*, now: datetime | None = None, limit: int = 50) -> dict[str, Any]:
    ensure_schema()
    now_value = (now or _utc_now()).astimezone(timezone.utc)
    now_iso = _iso_utc(now_value)
    bounded_limit = max(1, min(int(limit), 200))
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM reminders WHERE owner_id=? AND status IN ('scheduled','snoozed') "
            "AND trigger_at<=? ORDER BY trigger_at ASC, id ASC LIMIT ?",
            (_owner_id(), now_iso, bounded_limit),
        ).fetchall()

    processed: list[dict[str, Any]] = []
    for row in rows:
        item = _serialize(row)
        reminder_id = int(item["id"])
        claimed_at = db.now_iso()
        with db.get_connection() as conn:
            claimed = conn.execute(
                "UPDATE reminders SET status='dispatching', updated_at=? "
                "WHERE id=? AND owner_id=? AND status IN ('scheduled','snoozed')",
                (claimed_at, reminder_id, _owner_id()),
            ).rowcount
        if not claimed:
            continue

        target_url = str(item.get("target_url") or "/static/universe.html?view=reminders")
        separator = "&" if "?" in target_url else "?"
        if "reminder=" not in target_url:
            target_url = f"{target_url}{separator}reminder={reminder_id}"
        try:
            result = notifications.dispatch_notification(
                category="schedule_reminder",
                title=str(item["title"]),
                body=str(item["message"]),
                url=target_url,
                respect_preferences=True,
            )
            sent = int(result.get("sent") or 0)
            failed = int(result.get("failed") or 0)
            delivery_status = str(result.get("status") or ("sent" if sent else "processed"))
            errors = result.get("errors") or []
            final_status = "failed" if failed > 0 and sent == 0 else "fired"
            last_error = "; ".join(str(value) for value in errors[:3])[:2000] or None
            fired_at = db.now_iso()
            with db.get_connection() as conn:
                conn.execute(
                    "UPDATE reminders SET status=?, delivery_status=?, delivery_event_id=?, last_error=?, "
                    "fired_at=?, updated_at=? WHERE id=? AND owner_id=?",
                    (
                        final_status,
                        delivery_status,
                        result.get("event_id"),
                        last_error,
                        fired_at,
                        fired_at,
                        reminder_id,
                        _owner_id(),
                    ),
                )
            processed.append({"id": reminder_id, "status": final_status, "delivery": result})
        except Exception as exc:  # noqa: BLE001 - one failed reminder must not stop the scheduler
            error = f"{type(exc).__name__}: {exc}"[:2000]
            failed_at = db.now_iso()
            with db.get_connection() as conn:
                conn.execute(
                    "UPDATE reminders SET status='failed', delivery_status='exception', last_error=?, updated_at=? "
                    "WHERE id=? AND owner_id=?",
                    (error, failed_at, reminder_id, _owner_id()),
                )
            processed.append({"id": reminder_id, "status": "failed", "error": error})
    return {"processed": len(processed), "items": processed, "checked_at": now_iso}


def status_summary() -> dict[str, Any]:
    data = list_reminders(scope="all", limit=1)
    return {
        "scheduler_enabled": _scheduler_enabled(),
        "timezone": data["timezone"],
        "counts": data["counts"],
    }


def _scheduler_enabled() -> bool:
    return os.getenv("PETIT_REMINDER_SCHEDULER_ENABLED", "1").strip().casefold() not in {"0", "false", "off", "no"}


def _scheduler_interval() -> float:
    raw = os.getenv("PETIT_REMINDER_POLL_SECONDS", "15").strip()
    try:
        return max(1.0, min(float(raw), 300.0))
    except ValueError:
        return 15.0


class ReminderScheduler:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not _scheduler_enabled() or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, name="petit-reminders", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def run_once(self) -> dict[str, Any]:
        return process_due_reminders()

    def _run_loop(self) -> None:
        self.run_once()
        while not self._stop.wait(_scheduler_interval()):
            self.run_once()


_scheduler = ReminderScheduler()


@notifications.router.get("/reminders")
def get_reminders_api(scope: str = "upcoming", status: str | None = None, limit: int = 200) -> JSONResponse:
    try:
        data = list_reminders(scope=scope, status=status, limit=limit)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(data)


@notifications.router.post("/reminders")
def create_reminder_api(payload: ReminderCreateRequest) -> JSONResponse:
    try:
        item = create_reminder(**payload.model_dump())
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"created": True, "reminder": item}, status_code=201)


@notifications.router.get("/reminders/{reminder_id}")
def get_reminder_api(reminder_id: int) -> JSONResponse:
    item = get_reminder(reminder_id)
    if item is None:
        return JSONResponse({"error": "Reminder not found"}, status_code=404)
    return JSONResponse({"reminder": item})


@notifications.router.post("/reminders/{reminder_id}/complete")
def complete_reminder_api(reminder_id: int) -> JSONResponse:
    try:
        return JSONResponse(complete_reminder(reminder_id))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)


@notifications.router.post("/reminders/{reminder_id}/cancel")
def cancel_reminder_api(reminder_id: int) -> JSONResponse:
    try:
        return JSONResponse(cancel_reminder(reminder_id))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)


@notifications.router.post("/reminders/{reminder_id}/snooze")
def snooze_reminder_api(reminder_id: int, payload: ReminderSnoozeRequest) -> JSONResponse:
    try:
        return JSONResponse(snooze_reminder(reminder_id, payload.minutes))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)


@notifications.router.post("/reminders/run-due")
def run_due_reminders_api() -> dict[str, Any]:
    """Manual diagnostic endpoint; normal delivery is handled by the scheduler."""
    return process_due_reminders()


def _install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    def init_notifications_and_reminders() -> None:
        _ORIGINAL_NOTIFICATION_INIT_DB()
        ensure_schema(recover_dispatching=True)
        _scheduler.start()

    def notification_status_with_reminders() -> dict[str, Any]:
        result = _ORIGINAL_NOTIFICATION_STATUS()
        result["reminders"] = status_summary()
        return result

    notifications.init_db = init_notifications_and_reminders
    notifications.notification_status = notification_status_with_reminders
    atexit.register(_scheduler.stop)
    _INSTALLED = True


_install()
