"""FastAPI application: chat API + static frontend.

Run with:  uvicorn backend.main:app --reload
or:        python -m backend.main
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import logging
import json
import threading
import time
from uuid import uuid4

from . import agent, briefing, calendar_providers, calendar_sync, chroma_client, config, db, lmstudio_client, markdown_export, proactive, scheduler, tools, vault_indexer, worker
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
    request_id: str | None = None


class PendingAction(BaseModel):
    approval_id: str
    name: str
    arguments: dict[str, Any]


class ChatResponse(BaseModel):
    reply: str
    used_tools: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    model_route: dict[str, Any] | None = None
    request_id: str | None = None
    pending_actions: list[PendingAction] = Field(default_factory=list)


class ActionDecision(BaseModel):
    approved: bool


_pending_actions: dict[str, dict[str, Any]] = {}
_pending_actions_lock = threading.Lock()
_PENDING_ACTION_TTL_SECONDS = 600


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
            "embedding_stats": chroma_client.embedding_stats(),
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
            "sync": __import__("backend.tools.notion", fromlist=["status"]).status(),
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
            "read_adapter": "ics",
            "write_providers": calendar_providers.available(),
        },
        "model_routing": {
            "chat_model": config.CHAT_MODEL,
            "agent_model": config.AGENT_MODEL,
        },
    }


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    request_id = (req.request_id or "").strip() or uuid4().hex
    message = (req.message or "").strip()
    if not message:
        return ChatResponse(reply="", error="メッセージが空です。", request_id=request_id)

    started = time.monotonic()
    try:
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
    used_tools_str = ", ".join(t["name"] for t in used_tools) or None
    reply = (result.get("reply") or "").strip()
    pending_actions = _register_pending_actions(result.get("pending_actions") or [])
    if not reply:
        return ChatResponse(
            reply="",
            error="返答を生成できませんでした。もう一度短く言い換えてください。",
            model_route=model_route,
            request_id=request_id,
        )
    if result.get("persist", True):
        conv_id = db.save_conversation(
            user_text=message,
            assistant_text=reply,
            used_tools=used_tools_str,
        )
        threading.Thread(
            target=_persist_chat_artifacts,
            args=(conv_id, message, reply, used_tools_str),
            daemon=True,
        ).start()
    return ChatResponse(
        reply=reply,
        used_tools=used_tools,
        model_route=model_route,
        request_id=request_id,
        pending_actions=pending_actions,
    )


def _register_pending_actions(actions: list[dict[str, Any]]) -> list[PendingAction]:
    now = time.monotonic()
    registered: list[PendingAction] = []
    with _pending_actions_lock:
        expired = [key for key, value in _pending_actions.items() if now - value["created_at"] > _PENDING_ACTION_TTL_SECONDS]
        for key in expired:
            _pending_actions.pop(key, None)
        for action in actions:
            approval_id = uuid4().hex
            value = {
                "name": str(action["name"]),
                "arguments": dict(action.get("arguments") or {}),
                "created_at": now,
            }
            _pending_actions[approval_id] = value
            registered.append(PendingAction(approval_id=approval_id, name=value["name"], arguments=value["arguments"]))
    return registered


@app.post("/api/actions/{approval_id}", response_model=ChatResponse)
def decide_action(approval_id: str, decision: ActionDecision) -> ChatResponse:
    with _pending_actions_lock:
        action = _pending_actions.pop(approval_id, None)
    if action is None or time.monotonic() - action["created_at"] > _PENDING_ACTION_TTL_SECONDS:
        return ChatResponse(reply="", error="確認待ち操作が見つからないか、期限切れです。")
    if not decision.approved:
        return ChatResponse(reply="書き込みをキャンセルしました。")

    result = tools.dispatch(action["name"], action["arguments"])
    if _tool_result_failed(result):
        return ChatResponse(reply="", error=f"書き込みに失敗しました。{_short_tool_result(result)}")
    return ChatResponse(
        reply=f"確認された内容を実行しました。\n{_short_tool_result(result)}",
        used_tools=[{"name": action["name"], "arguments": action["arguments"]}],
    )


def _tool_result_failed(result: str) -> bool:
    if result.startswith("[error]"):
        return True
    try:
        data = json.loads(result)
    except json.JSONDecodeError:
        return False
    return isinstance(data, dict) and (
        bool(data.get("error"))
        or any(data.get(key) is False for key in ("ok", "created", "completed", "added", "saved", "updated"))
    )


def _short_tool_result(result: str) -> str:
    return result if len(result) <= 600 else result[:600] + "…"


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
