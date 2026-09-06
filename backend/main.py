"""FastAPI application composition root + static frontend.

Run with:  uvicorn backend.main:app --reload
or:        python -m backend.main
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import briefing, calendar_sync, chat, config, db, health, lifecycle, model_routing_api, notion_webhook, notifications, pending_actions, proactive, scheduler, shortcut_voice, vault_indexer, voice, work_sessions

app = FastAPI(title="PETIT", description="Personal AI Assistant (MVP)")
app.include_router(health.router)
app.include_router(model_routing_api.router)
app.include_router(notion_webhook.router)
app.include_router(notifications.router)
app.include_router(pending_actions.router)
app.include_router(work_sessions.router)
app.include_router(chat.router)
app.include_router(shortcut_voice.router)
app.include_router(voice.router)
lifecycle.register(app)


class JobAck(BaseModel):
    job_ids: list[int] = Field(default_factory=list)
    session_id: str


@app.post("/api/summarize")
def summarize() -> dict[str, Any]:
    """Manually trigger a summarization pass (otherwise runs on the scheduler)."""
    return scheduler.get_scheduler().run_once()


@app.get("/api/summaries")
def summaries(limit: int = 20) -> dict[str, Any]:
    return {
        "episodes": db.recent_episodes(limit=limit),
        "summaries": db.recent_summaries(limit=limit),
    }


@app.post("/api/vault/sync")
def sync_obsidian_vault(max_files: int | None = None) -> dict[str, Any]:
    return vault_indexer.index_configured_vaults(max_files=max_files)


@app.get("/api/proactive")
def proactive_opener() -> dict[str, Any]:
    """A line PETIT says first when the user opens the app (talks proactively)."""
    return proactive.generate_opener()


@app.get("/api/briefing")
def daily_briefing(date: str | None = None) -> dict[str, Any]:
    """Daily briefing: schedule + tasks + recent memory -> one next action."""
    return briefing.create_daily_briefing(date)


@app.post("/api/calendar/sync")
def sync_calendar(force: bool = True) -> dict[str, Any]:
    """Read configured calendar sources into the local schedule cache."""
    return calendar_sync.sync_if_configured(force=force)


@app.get("/api/conversations")
def conversations(limit: int = 20, session_id: str | None = None) -> dict[str, Any]:
    return {"conversations": db.recent_conversations(limit=limit, session_id=(session_id or "").strip() or None)}


@app.get("/api/jobs")
def jobs(limit: int = 10, session_id: str | None = None) -> dict[str, Any]:
    """Read completed jobs without mutating delivery state."""
    return {"jobs": db.undelivered_jobs(limit=limit, session_id=(session_id or "").strip() or None)}


@app.post("/api/jobs/ack")
def acknowledge_jobs(payload: JobAck) -> dict[str, Any]:
    session_id = payload.session_id.strip()
    if not session_id:
        return {"acknowledged": 0, "error": "session_id is required"}
    ids = [int(item) for item in payload.job_ids if int(item) > 0]
    db.mark_jobs_delivered(ids, session_id=session_id)
    return {"acknowledged": len(ids)}


# --- Static frontend ---------------------------------------------------------
# Mount assets under /static and serve index.html at the root.
if config.FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=config.FRONTEND_DIR), name="static")

    @app.get("/service-worker.js", include_in_schema=False)
    @app.get("/sw.js", include_in_schema=False)
    def service_worker() -> Any:
        service_worker_file = config.FRONTEND_DIR / "service-worker.js"
        if service_worker_file.exists():
            return FileResponse(
                service_worker_file,
                media_type="application/javascript",
                headers={
                    "Cache-Control": "no-cache",
                    "Service-Worker-Allowed": "/",
                },
            )
        return JSONResponse({"detail": "service worker not found"}, status_code=404)

    @app.get("/")
    def index() -> Any:
        index_file = config.FRONTEND_DIR / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return JSONResponse({"detail": "frontend not built"}, status_code=404)


def main() -> None:
    import uvicorn

    uvicorn.run("backend.main:app", host=config.HOST, port=config.PORT, reload=False)


if __name__ == "__main__":
    main()
