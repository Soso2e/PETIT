"""Support and utility HTTP endpoints outside the core chat flow."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from . import briefing, calendar_sync, db, proactive, request_context, scheduler, vault_indexer

router = APIRouter()


class JobAck(BaseModel):
    job_ids: list[int] = Field(default_factory=list)
    session_id: str


@router.post("/api/summarize")
def summarize() -> dict[str, Any]:
    """Manually trigger a summarization pass (otherwise runs on the scheduler)."""
    return scheduler.get_scheduler().run_once()


@router.get("/api/summaries")
def summaries(limit: int = 20) -> dict[str, Any]:
    return {
        "episodes": db.recent_episodes(limit=limit),
        "summaries": db.recent_summaries(limit=limit),
    }


@router.post("/api/vault/sync")
def sync_obsidian_vault(max_files: int | None = None) -> dict[str, Any]:
    return vault_indexer.index_configured_vaults(max_files=max_files)


@router.get("/api/proactive")
def proactive_opener(session_id: str | None = None) -> dict[str, Any]:
    """A line PETIT says first when the user opens the app (talks proactively)."""
    session_id = (session_id or "").strip() or None
    with request_context.bind(request_id=None, session_id=session_id):
        return proactive.generate_opener(session_id=session_id)


@router.get("/api/briefing")
def daily_briefing(date: str | None = None) -> dict[str, Any]:
    """Daily briefing: schedule + tasks + recent memory -> one next action."""
    return briefing.create_daily_briefing(date)


@router.post("/api/calendar/sync")
def sync_calendar(force: bool = True) -> dict[str, Any]:
    """Read configured calendar sources into the local schedule cache."""
    return calendar_sync.sync_if_configured(force=force)


@router.get("/api/conversations")
def conversations(limit: int = 20, session_id: str | None = None) -> dict[str, Any]:
    return {"conversations": db.recent_conversations(limit=limit, session_id=(session_id or "").strip() or None)}


@router.get("/api/jobs")
def jobs(limit: int = 10, session_id: str | None = None) -> dict[str, Any]:
    """Read completed jobs without mutating delivery state."""
    return {"jobs": db.undelivered_jobs(limit=limit, session_id=(session_id or "").strip() or None)}


@router.get("/api/activity/jobs")
def activity_jobs(response: Response, limit: int = 30) -> dict[str, Any]:
    """Show durable SQLite Job states without consuming delivery receipts.

    The shared setup middleware requires an authenticated administrator for
    every nonpublic /api endpoint, including this one.
    """
    response.headers["Cache-Control"] = "no-store"
    items = db.list_job_activity(limit)
    counts = {status: sum(row["status"] == status for row in items)
              for status in ("queued", "running", "done", "failed")}
    return {"jobs": items, "counts": counts, "scope": "recent_jobs",
            "running_is_persisted_state": True, "coding_jobs_included": False}


@router.post("/api/jobs/ack")
def acknowledge_jobs(payload: JobAck) -> dict[str, Any]:
    session_id = payload.session_id.strip()
    if not session_id:
        return {"acknowledged": 0, "error": "session_id is required"}
    ids = [int(item) for item in payload.job_ids if int(item) > 0]
    db.mark_jobs_delivered(ids, session_id=session_id)
    return {"acknowledged": len(ids)}
