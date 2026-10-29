"""Chat HTTP endpoint and persistence side effects."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import secrets
import logging
from uuid import uuid4
from typing import Literal

from fastapi import APIRouter, Request, Response
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
def chat(req: ChatRequest, request: Request = None, response: Response = None) -> ChatResponse:
    request_id = (req.request_id or "").strip() or uuid4().hex
    session_id = (req.session_id or "").strip() or None
    message = (req.message or "").strip()
    if not message and not req.attachment_ids:
        return ChatResponse(reply="", error="メッセージが空です。", request_id=request_id)

    from . import conversation_api, setup_store as settings
    is_admin = settings.valid_session(request.cookies.get("petit_admin", "")) if request is not None else False
    if not is_admin and req.attachment_ids:
        return ChatResponse(reply="", error="画像添付には管理者ログインが必要です。", request_id=request_id)
    if not is_admin and request is not None:
        # Never accept a user-supplied thread id for a guest conversation.
        guest_token = request.cookies.get("petit_guest", "")
        if len(guest_token) < 43 or len(guest_token) > 128 or not all(
            char.isalnum() or char in "-_" for char in guest_token
        ):
            guest_token = secrets.token_urlsafe(32)
            if response is not None:
                response.set_cookie(
                    "petit_guest", guest_token, httponly=True,
                    secure=request.url.scheme == "https", samesite="lax",
                    max_age=30 * 24 * 3600, path="/",
                )
        session_id = "guest-" + hashlib.sha256(guest_token.encode()).hexdigest()
    result = conversation_api.submit(session_id or uuid4().hex, request_id, message,
        source=req.source, conversation_mode=req.conversation_mode, attachment_ids=req.attachment_ids,
        is_admin=is_admin)
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
