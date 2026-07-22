"""FastAPI application: chat API + static frontend.

Run with:  uvicorn backend.main:app --reload
or:        python -m backend.main
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import json
import logging
import threading
import time
from uuid import uuid4

from . import agent, aivis_speech, briefing, calendar_providers, calendar_sync, chroma_client, config, db, lmstudio_client, markdown_export, model_routing, proactive, request_context, scheduler, tools, vault_indexer, worker
from .lmstudio_client import LMStudioError
from .notion_client import NotionError

log = logging.getLogger(__name__)

app = FastAPI(title="PETIT", description="Personal AI Assistant (MVP)")
_artifact_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="petit-artifacts")


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
    """Incrementally index SQLite memory/episodes and configured vaults."""
    try:
        mem_rows = db.all_memory()
        counts = chroma_client.sync_structured_data(mem_rows, db.all_episodes())
        vault_counts = vault_indexer.index_configured_vaults()
        if any(counts.values()) or vault_counts.get("chunks"):
            log.info("Chroma sync: %s vault=%s", counts, vault_counts)
    except Exception as exc:  # noqa: BLE001
        log.debug("Chroma startup sync skipped: %s", exc)


class ChatRequest(BaseModel):
    message: str
    history: list[dict[str, str]] | None = None
    request_id: str | None = None
    session_id: str | None = None


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


class JobAck(BaseModel):
    job_ids: list[int] = Field(default_factory=list)
    session_id: str


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=config.TTS_MAX_CHARS)


class ModelRoutingUpdate(BaseModel):
    chat: str | None = None
    agent: str | None = None


_pending_actions: dict[str, dict[str, Any]] = {}
_pending_actions_lock = threading.Lock()
_PENDING_ACTION_TTL_SECONDS = 600


@app.get("/api/health")
def health() -> dict[str, Any]:
    chat_health = lmstudio_client.health("chat")
    agent_health = lmstudio_client.health("agent")
    try:
        mem_count = chroma_client._collection("petit_memory").count()
        conv_count = chroma_client._collection("petit_conversations").count()
        episode_count = chroma_client._collection("petit_episodes").count()
        vault_count = chroma_client._collection("petit_vault").count()
        rag_info: dict[str, Any] = {
            "available": True,
            "embed_model": config.EMBED_MODEL,
            "indexed": {"memory": mem_count, "conversations_legacy": conv_count, "episodes": episode_count, "vault": vault_count},
            "embedding_stats": chroma_client.embedding_stats(),
        }
    except Exception:  # noqa: BLE001
        rag_info = {"available": False, "embed_model": config.EMBED_MODEL}

    with db.get_connection() as conn:
        calendar_cached = int(conn.execute("SELECT COUNT(*) FROM calendar_events_cache").fetchone()[0])

    routing_status = model_routing.public_status()
    return {
        "status": "ok",
        "tools": tools.registered_names(),
        # `lm_studio` is retained for older clients; new clients use the two
        # explicit model entries below.
        "lm_studio": {"ok": chat_health["server_ok"], "models": chat_health.get("models", []), "base_url": chat_health["base_url"]},
        "chat_model": chat_health,
        "agent_model": agent_health | {"fallback_available": bool(chat_health["server_ok"])},
        "notion": {
            "configured": config.notion_configured(),
            "sync": __import__("backend.tools.notion", fromlist=["status"]).status(),
        },
        "rag": rag_info,
        "auto_summary": {
            "enabled": config.AUTO_SUMMARY_ENABLED,
            "interval_hours": config.SUMMARY_INTERVAL_HOURS,
            "summaries": len(db.recent_summaries(limit=1000)), "episodes": len(db.recent_episodes(limit=1000)),
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
        "brain": vault_indexer.status(),
        "memory": {"episodes": len(db.recent_episodes(limit=1000)), "long_term": len(db.all_memory())},
        "model_routing": {
            **routing_status,
            "chat_model": chat_health["model"],
            "agent_model": agent_health["model"],
        },
        "tts": aivis_speech.status(check_engine=False),
    }


@app.get("/api/model-routing")
def get_model_routing() -> dict[str, Any]:
    return model_routing.public_status()


@app.post("/api/model-routing")
def update_model_routing(payload: ModelRoutingUpdate) -> dict[str, Any] | JSONResponse:
    updates = {
        route: value
        for route, value in (("chat", payload.chat), ("agent", payload.agent))
        if value is not None
    }
    try:
        result = model_routing.update_selection(updates)
    except model_routing.ModelRoutingError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    lmstudio_client.clear_health_cache()
    return result


@app.get("/api/tts/status")
def tts_status() -> dict[str, Any]:
    return aivis_speech.status(check_engine=True)


@app.post("/api/tts")
def synthesize_speech(payload: TTSRequest) -> Response:
    try:
        audio, style_id = aivis_speech.synthesize(payload.text)
    except aivis_speech.AivisSpeechError as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)
    return Response(
        content=audio,
        media_type="audio/wav",
        headers={
            "Cache-Control": "no-store",
            "X-PETIT-TTS-Provider": "aivis",
            "X-PETIT-TTS-Style-ID": str(style_id),
        },
    )


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
    pending_actions = _register_pending_actions(result.get("pending_actions") or [])
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
            action_name = str(action["name"])
            action_arguments = dict(action.get("arguments") or {})
            if config.USE_SONA_CORE and action_name == "add_schedule":
                from . import sona_core_add_schedule

                approval_id = sona_core_add_schedule.register_pending(action_arguments)
                registered.append(PendingAction(approval_id=approval_id, name=action_name, arguments=action_arguments))
                continue
            approval_id = uuid4().hex
            value = {
                "name": action_name,
                "arguments": action_arguments,
                "created_at": now,
            }
            _pending_actions[approval_id] = value
            registered.append(PendingAction(approval_id=approval_id, name=value["name"], arguments=value["arguments"]))
    return registered


@app.post("/api/actions/{approval_id}", response_model=ChatResponse)
def decide_action(approval_id: str, decision: ActionDecision) -> ChatResponse:
    if config.USE_SONA_CORE:
        try:
            from . import sona_core_add_schedule

            core_request = sona_core_add_schedule.get_pending(approval_id)
        except Exception:  # noqa: BLE001
            core_request = None
        if core_request is not None and core_request.invocation.call.name == "add_schedule":
            try:
                result = sona_core_add_schedule.decide_pending(approval_id, decision.approved)
            except (KeyError, ValueError) as exc:
                return ChatResponse(reply="", error=f"確認操作を実行できません。{exc}")
            if not decision.approved:
                return ChatResponse(reply="書き込みをキャンセルしました。")
            if result is None or result.status != "success":
                message = result.error.message if result and result.error else "schedule write failed"
                return ChatResponse(reply="", error=f"書き込みに失敗しました。{message}")
            rendered = json.dumps(result.data, ensure_ascii=False, default=str)
            return ChatResponse(
                reply=f"確認された内容を実行しました。\n{_short_tool_result(rendered)}",
                used_tools=[{"name": "add_schedule", "arguments": core_request.invocation.call.arguments}],
            )
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
