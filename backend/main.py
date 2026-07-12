"""FastAPI application: chat API + static frontend.

Run with:  uvicorn backend.main:app --reload
or:        python -m backend.main
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import logging
import threading

from . import agent, briefing, calendar_sync, chroma_client, config, db, lmstudio_client, markdown_export, proactive, scheduler, tools, vault_indexer, worker
from .lmstudio_client import LMStudioError
from .notion_client import NotionError

log = logging.getLogger(__name__)

app = FastAPI(title="PETIT", description="Personal AI Assistant (MVP)")


@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    # Sync existing SQLite data into Chroma in background (best-effort)
    threading.Thread(target=_chroma_sync, daemon=True).start()
    # Autonomous summarizer: fold conversations into memory every N hours
    if config.AUTO_SUMMARY_ENABLED:
        scheduler.get_scheduler().start()
    worker.get_worker().start()


@app.on_event("shutdown")
def _shutdown() -> None:
    if config.AUTO_SUMMARY_ENABLED:
        scheduler.get_scheduler().stop()
    worker.get_worker().stop()


def _chroma_sync() -> None:
    """Index SQLite memory, conversations, and configured Obsidian vaults."""
    try:
        mem_rows = db.all_memory()
        conv_rows = db.recent_conversations(limit=500)
        counts = chroma_client.sync_from_sqlite(mem_rows, conv_rows)
        vault_counts = vault_indexer.index_configured_vaults()
        if any(counts.values()) or vault_counts.get("chunks"):
            log.info("Chroma sync: %s vault=%s", counts, vault_counts)
    except Exception as exc:  # noqa: BLE001
        log.debug("Chroma startup sync skipped: %s", exc)


class ChatRequest(BaseModel):
    message: str
    history: list[dict[str, str]] | None = None


class ChatResponse(BaseModel):
    reply: str
    used_tools: list[dict[str, Any]] = []
    error: str | None = None
    model_route: dict[str, Any] | None = None


@app.get("/api/health")
def health() -> dict[str, Any]:
    try:
        mem_count = chroma_client._collection("petit_memory").count()
        conv_count = chroma_client._collection("petit_conversations").count()
        vault_count = chroma_client._collection("petit_vault").count()
        rag_info: dict[str, Any] = {
            "available": True,
            "embed_model": config.EMBED_MODEL,
            "indexed": {"memory": mem_count, "conversations": conv_count, "vault": vault_count},
        }
    except Exception:  # noqa: BLE001
        rag_info = {"available": False, "embed_model": config.EMBED_MODEL}

    with db.get_connection() as conn:
        calendar_cached = int(conn.execute("SELECT COUNT(*) FROM calendar_events_cache").fetchone()[0])

    return {
        "status": "ok",
        "tools": tools.registered_names(),
        "lm_studio": lmstudio_client.health(),
        "notion": {
            "configured": config.notion_configured(),
            "db_id": config.NOTION_TASKS_DB_ID[:8] + "…" if config.NOTION_TASKS_DB_ID else None,
        },
        "rag": rag_info,
        "auto_summary": {
            "enabled": config.AUTO_SUMMARY_ENABLED,
            "interval_hours": config.SUMMARY_INTERVAL_HOURS,
            "summaries": len(db.recent_summaries(limit=1000)),
        },
        "markdown": markdown_export.status(),
        "obsidian_vault": vault_indexer.status(),
        "calendar": {
            **calendar_sync.status(),
            "cached_events": calendar_cached,
            "google_calendar_connected_to_petit": calendar_sync.configured(),
        },
        "model_routing": {
            "chat_model": config.CHAT_MODEL,
            "agent_model": config.AGENT_MODEL,
        },
    }


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    message = (req.message or "").strip()
    if not message:
        return ChatResponse(reply="", error="メッセージが空です。")

    try:
        result = agent.run(message, history=req.history)
    except LMStudioError as exc:
        return ChatResponse(reply="", error=str(exc))

    used_tools_str = ", ".join(t["name"] for t in result["used_tools"]) or None
    conv_id = db.save_conversation(
        user_text=message,
        assistant_text=result["reply"],
        used_tools=used_tools_str,
    )
    # Index the conversation turn into Chroma (best-effort)
    chroma_client.add(
        "petit_conversations",
        doc_id=f"conv_{conv_id}",
        text=f"ユーザー: {message}\nPETIT: {result['reply']}",
        metadata={"timestamp": db.now_iso()},
    )
    # Mirror the turn into the Obsidian daily note (human-readable副本, best-effort)
    markdown_export.append_conversation_turn(
        user_text=message,
        assistant_text=result["reply"],
        used_tools=used_tools_str,
        timestamp=db.now_iso(),
    )
    return ChatResponse(
        reply=result["reply"],
        used_tools=result["used_tools"],
        model_route=result.get("model_route"),
    )


@app.post("/api/summarize")
def summarize() -> dict[str, Any]:
    """Manually trigger a summarization pass (otherwise runs on the scheduler)."""
    return scheduler.get_scheduler().run_once()


@app.get("/api/summaries")
def summaries(limit: int = 20) -> dict[str, Any]:
    return {"summaries": db.recent_summaries(limit=limit)}

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
def conversations(limit: int = 20) -> dict[str, Any]:
    return {"conversations": db.recent_conversations(limit=limit)}
@app.get("/api/jobs")
def jobs(limit: int = 10, mark_delivered: bool = True) -> dict[str, Any]:
    rows = db.undelivered_jobs(limit=limit)
    if mark_delivered:
        db.mark_jobs_delivered([int(row["id"]) for row in rows])
    return {"jobs": rows}


# --- Static frontend ---------------------------------------------------------
# Mount assets under /static and serve index.html at the root.
if config.FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=config.FRONTEND_DIR), name="static")

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
