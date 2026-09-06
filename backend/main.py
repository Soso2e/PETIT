"""FastAPI application: chat API + static frontend.

Run with:  uvicorn backend.main:app --reload
or:        python -m backend.main
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import logging
import time
from uuid import uuid4

from . import agent, briefing, calendar_sync, chroma_client, config, db, health, lifecycle, lmstudio_client, markdown_export, model_routing_api, notion_task_sync, notion_webhook, notifications, pending_actions, proactive, request_context, scheduler, shortcut_voice, vault_indexer, voice, work_sessions
from .chat_models import ChatResponse
from .lmstudio_client import LMStudioError

log = logging.getLogger(__name__)

app = FastAPI(title="PETIT", description="Personal AI Assistant (MVP)")
app.include_router(health.router)
app.include_router(model_routing_api.router)
app.include_router(notion_webhook.router)
app.include_router(notifications.router)
app.include_router(pending_actions.router)
app.include_router(work_sessions.router)
app.include_router(shortcut_voice.router)
app.include_router(voice.router)
lifecycle.register(app)
_artifact_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="petit-artifacts")


class ChatRequest(BaseModel):
    message: str
    history: list[dict[str, str]] | None = None
    request_id: str | None = None
    session_id: str | None = None


class JobAck(BaseModel):
    job_ids: list[int] = Field(default_factory=list)
    session_id: str


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    request_id = (req.request_id or "").strip() or uuid4().hex
    session_id = (req.session_id or "").strip() or None
    message = (req.message or "").strip()
    if not message:
        return ChatResponse(reply="", error="メッセージが空です。", request_id=request_id)

    started = time.monotonic()
    try:
        with request_context.bind(request_id=request_id, session_id=session_id):
            with lmstudio_client.observe_turn() as turn_metrics:
                result = agent.run(message, history=req.history)
    except LMStudioError as exc:
        return ChatResponse(reply="", error=str(exc), request_id=request_id)
    except Exception as exc:  # noqa: BLE001
        log.exception("chat failed request_id=%s", request_id)
        return ChatResponse(reply="", error=f"内部処理に失敗しました（{type(exc).__name__}）。", request_id=request_id)
    elapsed_ms = max(0, round((time.monotonic() - started) * 1000))
    model_route = dict(result.get("model_route") or {})
    model_route["elapsed_ms"] = elapsed_ms

    used_tools = result.get("used_tools") or []
    reply = (result.get("reply") or "").strip()
    registered_actions = pending_actions.register(result.get("pending_actions") or [])
    if not reply:
        return ChatResponse(
            reply="",
            error="返答を生成できませんでした。もう一度短く言い換えてください。",
            model_route=model_route,
            request_id=request_id,
        )
    tool_names = [str(item.get("name")) for item in used_tools]
    actual_route = model_route.get("actual_route", model_route.get("kind", "instant"))
    used_endpoint_route = "chat" if actual_route in {"chat", "chat_fallback"} else ("agent" if actual_route == "agent" else None)
    active_target = lmstudio_client.endpoint(used_endpoint_route) if used_endpoint_route else None
    observed_model = turn_metrics["models"][-1] if turn_metrics.get("models") else model_route.get("model")
    observed_profile = turn_metrics["profiles"][-1] if turn_metrics.get("profiles") else (active_target or {}).get("profile")
    model_route["observability"] = {
        "request_id": request_id,
        "requested_route": model_route.get("requested_route", model_route.get("kind", "instant")),
        "actual_route": actual_route,
        "model": observed_model,
        "profile": observed_profile,
        "provider": (active_target or {}).get("provider"),
        "base_url_id": model_route.get("base_url_id"),
        "tools": tool_names,
        "llm_calls": turn_metrics["llm_calls"],
        "embedding_calls": 0,
        "notion_sync": __import__("backend.tools.notion", fromlist=["status"]).status(),
        "notion_task_live_sync": notion_task_sync.status(),
        "calendar_sync": calendar_sync.status(),
        "brain_references": int("search_brain_notes" in tool_names),
        "memory_references": int("search_memory" in tool_names),
        "fallback": model_route.get("actual_route") == "chat_fallback",
        "elapsed_ms": elapsed_ms,
        "error_type": None,
    }
    log.info("chat request_id=%s requested=%s actual=%s model=%s endpoint=%s tools=%s llm_calls=%s embedding_calls=0 fallback=%s elapsed_ms=%s error_type=%s",
             request_id, model_route["observability"]["requested_route"], model_route["observability"]["actual_route"],
             model_route["observability"]["model"], model_route["observability"]["base_url_id"], tool_names,
             turn_metrics["llm_calls"], model_route["observability"]["fallback"], elapsed_ms, None)
    used_tools_str = ", ".join(t["name"] for t in used_tools) or None
    if result.get("persist", True):
        conv_id = db.save_conversation(
            user_text=message,
            assistant_text=reply,
            used_tools=used_tools_str,
            session_id=session_id,
        )
        _artifact_executor.submit(_persist_chat_artifacts, conv_id, message, reply, used_tools_str)
    return ChatResponse(
        reply=reply,
        used_tools=used_tools,
        model_route=model_route,
        request_id=request_id,
        pending_actions=registered_actions,
    )


def _persist_chat_artifacts(conv_id: int, message: str, reply: str, used_tools: str | None) -> None:
    """Best-effort side effects that must not block chat responses."""
    timestamp = db.now_iso()
    # Casual chat is stored as history but does not trigger RAG embedding.
    if used_tools:
        chroma_client.add(
            "petit_conversations",
            doc_id=f"conv_{conv_id}",
            text=f"ユーザー: {message}\nPETIT: {reply}",
            metadata={"timestamp": timestamp},
        )
    markdown_export.append_conversation_turn(
        user_text=message,
        assistant_text=reply,
        used_tools=used_tools,
        timestamp=timestamp,
    )


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
