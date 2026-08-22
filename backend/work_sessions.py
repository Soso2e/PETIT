"""Server-side work-session check-ins, daily summaries, and inactivity timeout."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import db, notifications

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/work-sessions", tags=["work-sessions"])

CHECK_INTERVAL_MINUTES = 20
TOKYO = ZoneInfo("Asia/Tokyo")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS work_sessions (
    session_id              TEXT PRIMARY KEY,
    task_id                 TEXT,
    task                    TEXT NOT NULL,
    project_id              TEXT,
    status                  TEXT NOT NULL DEFAULT 'active',
    started_at              TEXT NOT NULL,
    paused_at               TEXT,
    paused_total_seconds    INTEGER NOT NULL DEFAULT 0,
    ended_at                TEXT,
    next_check_at           TEXT,
    awaiting_response_since TEXT,
    last_response_at        TEXT,
    last_notification_at    TEXT,
    updated_at              TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_work_sessions_due
ON work_sessions(status, next_check_at);
CREATE INDEX IF NOT EXISTS idx_work_sessions_started
ON work_sessions(started_at);
CREATE TABLE IF NOT EXISTS work_session_events (
    event_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    metadata_json TEXT,
    FOREIGN KEY(session_id) REFERENCES work_sessions(session_id)
);
CREATE INDEX IF NOT EXISTS idx_work_session_events_session_time
ON work_session_events(session_id, occurred_at, event_id);
"""


class WorkSessionStart(BaseModel):
    session_id: str = Field(min_length=1, max_length=120)
    task_id: str | None = Field(default=None, max_length=160)
    task: str = Field(min_length=1, max_length=160)
    project_id: str | None = Field(default=None, max_length=160)


def _now(value: datetime | None = None) -> datetime:
    return (value or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def ensure_schema() -> None:
    with db.get_connection() as conn:
        conn.executescript(_SCHEMA)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(work_sessions)").fetchall()}
        if "project_id" not in columns:
            conn.execute("ALTER TABLE work_sessions ADD COLUMN project_id TEXT")
        if "task_id" not in columns:
            conn.execute("ALTER TABLE work_sessions ADD COLUMN task_id TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_work_sessions_task ON work_sessions(task_id, started_at)"
        )


def _record_event(
    conn: Any,
    session_id: str,
    event_type: str,
    occurred_at: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        "INSERT INTO work_session_events(session_id, event_type, occurred_at, metadata_json) VALUES (?, ?, ?, ?)",
        (session_id, event_type, occurred_at, json.dumps(metadata, ensure_ascii=False) if metadata else None),
    )


def _events(session_id: str) -> list[dict[str, Any]]:
    return _events_for_sessions([session_id]).get(session_id, [])


def _events_for_sessions(session_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    identifiers = list(dict.fromkeys(str(value) for value in session_ids if str(value)))
    if not identifiers:
        return {}
    ensure_schema()
    placeholders = ",".join("?" for _ in identifiers)
    with db.get_connection() as conn:
        rows = conn.execute(
            f"SELECT session_id, event_type, occurred_at, metadata_json FROM work_session_events "
            f"WHERE session_id IN ({placeholders}) ORDER BY session_id, occurred_at, event_id",
            identifiers,
        ).fetchall()
    grouped = {session_id: [] for session_id in identifiers}
    for row in rows:
        event = dict(row)
        grouped[str(event.pop("session_id"))].append(event)
    return grouped


def _row(session_id: str) -> dict[str, Any] | None:
    ensure_schema()
    with db.get_connection() as conn:
        row = conn.execute("SELECT * FROM work_sessions WHERE session_id=?", (session_id,)).fetchone()
    return dict(row) if row else None


def active_session() -> dict[str, Any] | None:
    ensure_schema()
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM work_sessions WHERE status IN ('active', 'paused') ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
    return session_snapshot(dict(row)) if row else None


def start_session(
    session_id: str,
    task: str,
    *,
    task_id: str | None = None,
    project_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    ensure_schema()
    current = _now(now)
    current_iso = _iso(current)
    next_check = _iso(current + timedelta(minutes=CHECK_INTERVAL_MINUTES))
    with db.get_connection() as conn:
        replaced = conn.execute(
            "SELECT session_id FROM work_sessions WHERE status IN ('active', 'paused') AND session_id<>?",
            (session_id,),
        ).fetchall()
        conn.execute(
            "UPDATE work_sessions SET status='ended', ended_at=?, next_check_at=NULL, "
            "awaiting_response_since=NULL, updated_at=? WHERE status IN ('active', 'paused') AND session_id<>?",
            (current_iso, current_iso, session_id),
        )
        for row in replaced:
            _record_event(conn, str(row["session_id"]), "ended", current_iso, {"reason": "replaced"})
        conn.execute("DELETE FROM work_session_events WHERE session_id=?", (session_id,))
        conn.execute(
            "INSERT INTO work_sessions(session_id, task_id, task, project_id, status, started_at, next_check_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'active', ?, ?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET task_id=excluded.task_id, task=excluded.task, "
            "project_id=excluded.project_id, status='active', "
            "started_at=excluded.started_at, paused_at=NULL, paused_total_seconds=0, ended_at=NULL, "
            "next_check_at=excluded.next_check_at, awaiting_response_since=NULL, last_response_at=NULL, "
            "last_notification_at=NULL, updated_at=excluded.updated_at",
            (
                session_id,
                (task_id or "").strip() or None,
                task.strip(),
                (project_id or "").strip() or None,
                current_iso,
                next_check,
                current_iso,
            ),
        )
        _record_event(conn, session_id, "started", current_iso)
    return session_snapshot(_row(session_id), now=current) or {}


def respond(session_id: str, *, now: datetime | None = None) -> dict[str, Any] | None:
    current = _now(now)
    current_iso = _iso(current)
    next_check = _iso(current + timedelta(minutes=CHECK_INTERVAL_MINUTES))
    ensure_schema()
    with db.get_connection() as conn:
        changed = conn.execute(
            "UPDATE work_sessions SET awaiting_response_since=NULL, last_response_at=?, "
            "next_check_at=?, updated_at=? WHERE session_id=? AND status='active' "
            "AND awaiting_response_since IS NOT NULL",
            (current_iso, next_check, current_iso, session_id),
        ).rowcount
        if changed:
            _record_event(conn, session_id, "responded", current_iso)
    return session_snapshot(_row(session_id), now=current) if changed else None


def pause_session(session_id: str, *, now: datetime | None = None) -> dict[str, Any] | None:
    current = _now(now)
    current_iso = _iso(current)
    ensure_schema()
    with db.get_connection() as conn:
        changed = conn.execute(
            "UPDATE work_sessions SET status='paused', paused_at=?, next_check_at=NULL, "
            "awaiting_response_since=NULL, updated_at=? WHERE session_id=? AND status='active'",
            (current_iso, current_iso, session_id),
        ).rowcount
        if changed:
            _record_event(conn, session_id, "paused", current_iso)
    return session_snapshot(_row(session_id), now=current) if changed else None


def resume_session(session_id: str, *, now: datetime | None = None) -> dict[str, Any] | None:
    current = _now(now)
    current_iso = _iso(current)
    ensure_schema()
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT paused_at, paused_total_seconds FROM work_sessions WHERE session_id=? AND status='paused'",
            (session_id,),
        ).fetchone()
        if not row:
            return None
        paused_at = datetime.fromisoformat(row["paused_at"])
        paused_seconds = int(row["paused_total_seconds"] or 0) + max(0, int((current - paused_at).total_seconds()))
        conn.execute(
            "UPDATE work_sessions SET status='active', paused_at=NULL, paused_total_seconds=?, "
            "next_check_at=?, awaiting_response_since=NULL, updated_at=? WHERE session_id=?",
            (paused_seconds, _iso(current + timedelta(minutes=CHECK_INTERVAL_MINUTES)), current_iso, session_id),
        )
        _record_event(conn, session_id, "resumed", current_iso)
    return session_snapshot(_row(session_id), now=current)


def end_session(session_id: str, *, now: datetime | None = None, status: str = "ended") -> dict[str, Any] | None:
    current = _now(now)
    current_iso = _iso(current)
    ensure_schema()
    with db.get_connection() as conn:
        changed = conn.execute(
            "UPDATE work_sessions SET status=?, ended_at=?, next_check_at=NULL, "
            "awaiting_response_since=NULL, updated_at=? WHERE session_id=? AND status IN ('active', 'paused')",
            (status, current_iso, current_iso, session_id),
        ).rowcount
        if changed:
            _record_event(conn, session_id, status, current_iso)
    return session_snapshot(_row(session_id), now=current) if changed else None


def _event_overlap_seconds(
    events: list[dict[str, Any]],
    start: datetime,
    end: datetime,
    now: datetime,
) -> int | None:
    if not any(event.get("event_type") == "started" for event in events):
        return None
    active_since: datetime | None = None
    total = 0
    for event in events:
        occurred_at = _parse(event.get("occurred_at"))
        if occurred_at is None:
            continue
        event_type = str(event.get("event_type") or "")
        if event_type in {"started", "resumed"}:
            if active_since is None:
                active_since = occurred_at
        elif event_type in {"paused", "ended", "auto_stopped"} and active_since is not None:
            total += max(0, int((min(occurred_at, end) - max(active_since, start)).total_seconds()))
            active_since = None
    if active_since is not None:
        total += max(0, int((min(now, end) - max(active_since, start)).total_seconds()))
    return total


def _overlap_seconds(
    row: dict[str, Any],
    start: datetime,
    end: datetime,
    now: datetime,
    *,
    events: list[dict[str, Any]] | None = None,
) -> int:
    session_events = _events(str(row["session_id"])) if events is None else events
    event_total = _event_overlap_seconds(session_events, start, end, now)
    if event_total is not None:
        return event_total
    session_start = _parse(row.get("started_at"))
    if not session_start:
        return 0
    session_end = _parse(row.get("ended_at")) or now
    if row.get("status") == "paused":
        session_end = _parse(row.get("paused_at")) or session_end
    overlap_start = max(session_start, start)
    overlap_end = min(session_end, end)
    if overlap_end <= overlap_start:
        return 0
    total = int((overlap_end - overlap_start).total_seconds())
    paused_total = int(row.get("paused_total_seconds") or 0)
    if session_start >= start and session_end <= end:
        total -= paused_total
    return max(0, total)


def session_snapshot(row: dict[str, Any] | None, *, now: datetime | None = None) -> dict[str, Any] | None:
    if not row:
        return None
    current = _now(now)
    session_start = _parse(row.get("started_at")) or current
    result = dict(row)
    result["elapsed_seconds"] = _overlap_seconds(result, session_start, current, current)
    return result


def today_summary(*, now: datetime | None = None) -> dict[str, Any]:
    current = _now(now)
    local_now = current.astimezone(TOKYO)
    day_start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end_local = day_start_local + timedelta(days=1)
    day_start = day_start_local.astimezone(timezone.utc)
    day_end = day_end_local.astimezone(timezone.utc)
    ensure_schema()
    with db.get_connection() as conn:
        rows = [dict(row) for row in conn.execute(
            "SELECT * FROM work_sessions WHERE started_at < ? AND COALESCE(ended_at, ?) > ? ORDER BY started_at ASC",
            (_iso(day_end), _iso(current), _iso(day_start)),
        ).fetchall()]
    events_by_session = _events_for_sessions([str(row["session_id"]) for row in rows])

    sessions: list[dict[str, Any]] = []
    project_totals: dict[str, int] = {}
    task_totals: dict[str, dict[str, Any]] = {}
    total_seconds = 0
    for row in rows:
        seconds = _overlap_seconds(
            row, day_start, day_end, current, events=events_by_session.get(str(row["session_id"]), [])
        )
        if seconds <= 0:
            continue
        project = str(row.get("project_id") or row.get("task") or "未分類")
        task_key = str(row.get("task_id") or row.get("task") or "未分類")
        total_seconds += seconds
        project_totals[project] = project_totals.get(project, 0) + seconds
        task_total = task_totals.setdefault(
            task_key,
            {
                "task_id": row.get("task_id"),
                "task": row.get("task") or "未分類",
                "project_id": row.get("project_id"),
                "elapsed_seconds": 0,
            },
        )
        task_total["elapsed_seconds"] += seconds
        sessions.append({
            "session_id": row["session_id"],
            "task_id": row.get("task_id"),
            "task": row["task"],
            "project_id": row.get("project_id"),
            "status": row["status"],
            "started_at": row["started_at"],
            "ended_at": row.get("ended_at"),
            "elapsed_seconds": seconds,
        })
    return {
        "date": day_start_local.date().isoformat(),
        "timezone": "Asia/Tokyo",
        "total_seconds": total_seconds,
        "sessions": sessions,
        "projects": [
            {"project": project, "elapsed_seconds": seconds}
            for project, seconds in sorted(project_totals.items(), key=lambda item: item[1], reverse=True)
        ],
        "tasks": sorted(task_totals.values(), key=lambda item: item["elapsed_seconds"], reverse=True),
        "active": active_session(),
    }


def period_summary(days: int = 7, *, now: datetime | None = None) -> dict[str, Any]:
    """Return daily, task, and project totals for the most recent local calendar days."""
    bounded_days = max(1, min(int(days), 90))
    current = _now(now)
    local_now = current.astimezone(TOKYO)
    end_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    start_local = end_local - timedelta(days=bounded_days)
    start = start_local.astimezone(timezone.utc)
    end = end_local.astimezone(timezone.utc)
    ensure_schema()
    with db.get_connection() as conn:
        rows = [dict(row) for row in conn.execute(
            "SELECT * FROM work_sessions WHERE started_at < ? AND COALESCE(ended_at, ?) > ? ORDER BY started_at ASC",
            (_iso(end), _iso(current), _iso(start)),
        ).fetchall()]
    events_by_session = _events_for_sessions([str(row["session_id"]) for row in rows])

    task_totals: dict[str, dict[str, Any]] = {}
    project_totals: dict[str, int] = {}
    daily: list[dict[str, Any]] = []
    total_seconds = 0
    for offset in range(bounded_days):
        day_start_local = start_local + timedelta(days=offset)
        day_end_local = day_start_local + timedelta(days=1)
        day_start = day_start_local.astimezone(timezone.utc)
        day_end = day_end_local.astimezone(timezone.utc)
        seconds = sum(
            _overlap_seconds(
                row,
                day_start,
                day_end,
                current,
                events=events_by_session.get(str(row["session_id"]), []),
            )
            for row in rows
        )
        daily.append({"date": day_start_local.date().isoformat(), "elapsed_seconds": seconds})

    for row in rows:
        seconds = _overlap_seconds(
            row, start, end, current, events=events_by_session.get(str(row["session_id"]), [])
        )
        if seconds <= 0:
            continue
        total_seconds += seconds
        task_key = str(row.get("task_id") or row.get("task") or "未分類")
        task_total = task_totals.setdefault(
            task_key,
            {
                "task_id": row.get("task_id"),
                "task": row.get("task") or "未分類",
                "project_id": row.get("project_id"),
                "elapsed_seconds": 0,
                "session_count": 0,
            },
        )
        task_total["elapsed_seconds"] += seconds
        task_total["session_count"] += 1
        project = str(row.get("project_id") or "未分類")
        project_totals[project] = project_totals.get(project, 0) + seconds

    return {
        "date_from": start_local.date().isoformat(),
        "date_to": (end_local - timedelta(days=1)).date().isoformat(),
        "timezone": "Asia/Tokyo",
        "days": bounded_days,
        "total_seconds": total_seconds,
        "daily": daily,
        "tasks": sorted(task_totals.values(), key=lambda item: item["elapsed_seconds"], reverse=True),
        "projects": [
            {"project": project, "elapsed_seconds": seconds}
            for project, seconds in sorted(project_totals.items(), key=lambda item: item[1], reverse=True)
        ],
        "active": active_session(),
    }


def run_due_checks(
    *,
    now: datetime | None = None,
    dispatch: Callable[..., dict[str, Any]] = notifications.dispatch_notification,
) -> dict[str, int]:
    """Send a check-in, then stop the session at the next due time without a response."""
    current = _now(now)
    current_iso = _iso(current)
    due: list[dict[str, Any]] = []
    ensure_schema()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM work_sessions WHERE status='active' AND next_check_at IS NOT NULL AND next_check_at<=?",
            (current_iso,),
        ).fetchall()
        for raw in rows:
            row = dict(raw)
            if row["awaiting_response_since"]:
                conn.execute(
                    "UPDATE work_sessions SET status='auto_stopped', ended_at=?, next_check_at=NULL, "
                    "awaiting_response_since=NULL, updated_at=? WHERE session_id=? AND status='active'",
                    (current_iso, current_iso, row["session_id"]),
                )
                _record_event(conn, row["session_id"], "auto_stopped", current_iso)
                row["event"] = "auto_stopped"
            else:
                conn.execute(
                    "UPDATE work_sessions SET awaiting_response_since=?, last_notification_at=?, "
                    "next_check_at=?, updated_at=? WHERE session_id=? AND status='active'",
                    (current_iso, current_iso, _iso(current + timedelta(minutes=CHECK_INTERVAL_MINUTES)), current_iso, row["session_id"]),
                )
                _record_event(conn, row["session_id"], "check_in", current_iso)
                row["event"] = "check_in"
            due.append(row)

    counts = {"checked": 0, "auto_stopped": 0}
    for row in due:
        if row["event"] == "check_in":
            counts["checked"] += 1
            title = "PETIT 作業チェック"
            body = f"「{row['task']}」を始めて20分。進捗どう？まだ続けてる？返事がなければ20分後に一旦止めるよ。"
        else:
            counts["auto_stopped"] += 1
            title = "PETIT 作業を一旦停止"
            body = f"「{row['task']}」は返事がなかったので、時間の加算を止めたよ。続けるときにもう一度開始してね。"
        try:
            dispatch(category="work_session", title=title, body=body, url="/", respect_preferences=True)
        except Exception as exc:  # noqa: BLE001
            log.warning("Work-session notification failed: %s", exc)
    return counts


@router.post("/start")
def start_work_session(payload: WorkSessionStart) -> dict[str, Any]:
    return {
        "session": start_session(
            payload.session_id,
            payload.task,
            task_id=payload.task_id,
            project_id=payload.project_id,
        )
    }


@router.get("/active")
def get_active_work_session() -> dict[str, Any]:
    return {"session": active_session()}


@router.get("/today")
def get_today_work_sessions() -> dict[str, Any]:
    return today_summary()


@router.get("/summary")
def get_work_session_summary(days: int = Query(default=7, ge=1, le=90)) -> dict[str, Any]:
    return period_summary(days)


@router.get("/{session_id}")
def get_work_session(session_id: str) -> JSONResponse:
    session = _row(session_id)
    if not session:
        return JSONResponse({"error": "作業セッションが見つかりません。"}, status_code=404)
    return JSONResponse({"session": session_snapshot(session)})


def _update_response(session: dict[str, Any] | None) -> JSONResponse:
    if not session:
        return JSONResponse({"error": "進行中の作業セッションが見つかりません。"}, status_code=409)
    return JSONResponse({"session": session})


@router.post("/{session_id}/respond")
def respond_to_work_session(session_id: str) -> JSONResponse:
    return _update_response(respond(session_id))


@router.post("/{session_id}/pause")
def pause_work_session(session_id: str) -> JSONResponse:
    return _update_response(pause_session(session_id))


@router.post("/{session_id}/resume")
def resume_work_session(session_id: str) -> JSONResponse:
    return _update_response(resume_session(session_id))


@router.post("/{session_id}/end")
def end_work_session(session_id: str) -> JSONResponse:
    return _update_response(end_session(session_id))
