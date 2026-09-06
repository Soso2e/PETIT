"""Chat HTTP endpoint and persistence side effects."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import logging
import time
from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel

from . import (
    agent,
    calendar_sync,
    chroma_client,
    conversation_state,
    db,
    lmstudio_client,
    markdown_export,
    notion_task_sync,
    pending_actions,
    request_context,
)
from .chat_models import ChatResponse
from .lmstudio_client import LMStudioError

log = logging.getLogger(__name__)
router = APIRouter()
_artifact_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="petit-artifacts")


class ChatRequest(BaseModel):
    message: str
    history: list[dict[str, str]] | None = None
    request_id: str | None = None
    session_id: str | None = None


@router.post("/api/chat", response_model=ChatResponse)
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
        "conversation_state_chars": int(model_route.get("conversation_state_chars") or 0),
        "history_chars": int(model_route.get("history_chars") or 0),
        "history_messages": int(model_route.get("history_messages") or 0),
        "fallback": model_route.get("actual_route") == "chat_fallback",
        "elapsed_ms": elapsed_ms,
        "error_type": None,
    }
    log.info(
        "chat request_id=%s requested=%s actual=%s model=%s endpoint=%s tools=%s llm_calls=%s state_chars=%s history_chars=%s fallback=%s elapsed_ms=%s error_type=%s",
        request_id,
        model_route["observability"]["requested_route"],
        model_route["observability"]["actual_route"],
        model_route["observability"]["model"],
        model_route["observability"]["base_url_id"],
        tool_names,
        turn_metrics["llm_calls"],
        model_route["observability"]["conversation_state_chars"],
        model_route["observability"]["history_chars"],
        model_route["observability"]["fallback"],
        elapsed_ms,
        None,
    )

    used_tools_str = ", ".join(t["name"] for t in used_tools) or None
    if result.get("persist", True):
        conv_id = db.save_conversation(
            user_text=message,
            assistant_text=reply,
            used_tools=used_tools_str,
            session_id=session_id,
        )
        if session_id:
            try:
                conversation_state.update_after_turn(
                    session_id,
                    user_text=message,
                    assistant_text=reply,
                )
            except Exception:  # noqa: BLE001
                # State is an optimization. It must never make a successful chat fail.
                log.exception("conversation state update failed session_id=%s", session_id)
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
