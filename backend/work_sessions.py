"""Server-side work-session check-ins, daily summaries, and inactivity timeout."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from fastapi import APIRouter
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
"""


class WorkSessionStart(BaseModel):
    session_id: str = Field(min_length=1, max_length=120)
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
    return dict(row) if row else None


def start_session(
    session_id: str,
    task: str,
    *,
    project_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    ensure_schema()
    current = _now(now)
    current_iso = _iso(current)
    next_check = _iso(current + timedelta(minutes=CHECK_INTERVAL_MINUTES))
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE work_sessions SET status='ended', ended_at=?, next_check_at=NULL, "
            "awaiting_response_since=NULL, updated_at=? WHERE status IN ('active', 'paused') AND session_id<>?",
            (current_iso, current_iso, session_id),
        )
        conn.execute(
            "INSERT INTO work_sessions(session_id, task, project_id, status, started_at, next_check_at, updated_at) "
            "VALUES (?, ?, ?, 'active', ?, ?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET task=excluded.task, project_id=excluded.project_id, status='active', "
            "started_at=excluded.started_at, paused_at=NULL, paused_total_seconds=0, ended_at=NULL, "
            "next_check_at=excluded.next_check_at, awaiting_response_since=NULL, last_response_at=NULL, "
            "last_notification_at=NULL, updated_at=excluded.updated_at",
            (session_id, task.strip(), (project_id or "").strip() or None, current_iso, next_check, current_iso),
        )
    return _row(session_id) or {}


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
    return _row(session_id) if changed else None


def pause_session(session_id: str, *, now: datetime | None = None) -> dict[str, Any] | None:
    current_iso = _iso(_now(now))
    ensure_schema()
    with db.get_connection() as conn:
        changed = conn.execute(
            "UPDATE work_sessions SET status='paused', paused_at=?, next_check_at=NULL, "
            "awaiting_response_since=NULL, updated_at=? WHERE session_id=? AND status='active'",
            (current_iso, current_iso, session_id),
        ).rowcount
    return _row(session_id) if changed else None


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
    return _row(session_id)


def end_session(session_id: str, *, now: datetime | None = None, status: str = "ended") -> dict[str, Any] | None:
    current_iso = _iso(_now(now))
    ensure_schema()
    with db.get_connection() as conn:
        changed = conn.execute(
            "UPDATE work_sessions SET status=?, ended_at=?, next_check_at=NULL, "
            "awaiting_response_since=NULL, updated_at=? WHERE session_id=? AND status IN ('active', 'paused')",
            (status, current_iso, current_iso, session_id),
        ).rowcount
    return _row(session_id) if changed else None


def _overlap_seconds(row: dict[str, Any], start: datetime, end: datetime, now: datetime) -> int:
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

    sessions: list[dict[str, Any]] = []
    project_totals: dict[str, int] = {}
    total_seconds = 0
    for row in rows:
        seconds = _overlap_seconds(row, day_start, day_end, current)
        if seconds <= 0:
            continue
        project = str(row.get("project_id") or row.get("task") or "未分類")
        total_seconds += seconds
        project_totals[project] = project_totals.get(project, 0) + seconds
        sessions.append({
            "session_id": row["session_id"],
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
                row["event"] = "auto_stopped"
            else:
                conn.execute(
                    "UPDATE work_sessions SET awaiting_response_since=?, last_notification_at=?, "
                    "next_check_at=?, updated_at=? WHERE session_id=? AND status='active'",
                    (current_iso, current_iso, _iso(current + timedelta(minutes=CHECK_INTERVAL_MINUTES)), current_iso, row["session_id"]),
                )
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
    return {"session": start_session(payload.session_id, payload.task, project_id=payload.project_id)}


@router.get("/active")
def get_active_work_session() -> dict[str, Any]:
    return {"session": active_session()}


@router.get("/today")
def get_today_work_sessions() -> dict[str, Any]:
    return today_summary()


@router.get("/{session_id}")
def get_work_session(session_id: str) -> JSONResponse:
    session = _row(session_id)
    if not session:
        return JSONResponse({"error": "作業セッションが見つかりません。"}, status_code=404)
    return JSONResponse({"session": session})


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
