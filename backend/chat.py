"""Chat HTTP endpoint and persistence side effects."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import logging
from uuid import uuid4
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from . import chroma_client, markdown_export, db
from .chat_models import ChatResponse

log = logging.getLogger(__name__)
router = APIRouter()
_artifact_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="petit-artifacts")


class ChatRequest(BaseModel):
    message: str = Field(default="", max_length=20000)
    attachment_ids: list[str] = Field(default_factory=list, max_length=4)
    history: list[dict[str, str]] | None = None
    request_id: str | None = Field(default=None, max_length=200)
    session_id: str | None = Field(default=None, max_length=200)
    source: Literal["web", "desktop", "voice", "discord"] = "web"
    conversation_mode: Literal["text", "voice"] = "text"


@router.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    request_id = (req.request_id or "").strip() or uuid4().hex
    session_id = (req.session_id or "").strip() or None
    message = (req.message or "").strip()
    if not message and not req.attachment_ids:
        return ChatResponse(reply="", error="メッセージが空です。", request_id=request_id)

    from . import conversation_api
    result = conversation_api.submit(session_id or uuid4().hex, request_id, message,
        source=req.source, conversation_mode=req.conversation_mode, attachment_ids=req.attachment_ids)
    return ChatResponse(**result)


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
