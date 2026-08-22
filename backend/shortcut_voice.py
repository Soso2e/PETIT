"""iOS Vocal Shortcuts / Shortcuts entrypoint for PETIT.

Wake-word detection and speech-to-text stay on iOS. This module only accepts
recognized text and delegates it to the existing ``/api/chat`` implementation so
routing, confirmation, persistence, and observability remain identical to the PWA.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["voice-shortcut"])

SOURCE = "ios_shortcut"
DEFAULT_SESSION_ID = "ios-shortcut"
MAX_MESSAGE_CHARS = 4000
MAX_SESSION_ID_CHARS = 128


class VoiceShortcutRequest(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    session_id: str | None = Field(default=None, max_length=MAX_SESSION_ID_CHARS)


class VoiceShortcutResponse(BaseModel):
    ok: bool
    reply: str = ""
    source: str = SOURCE
    request_id: str | None = None
    needs_confirmation: bool = False
    pending_actions: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


def _model_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return dict(value.model_dump())
    if hasattr(value, "dict"):
        return dict(value.dict())
    return dict(value)


@router.post("/voice", response_model=VoiceShortcutResponse)
def voice_shortcut(payload: VoiceShortcutRequest) -> VoiceShortcutResponse:
    """Send iOS-dictated text through PETIT's normal chat path.

    The endpoint deliberately does not approve pending writes. If the normal chat
    flow requires confirmation, that state is surfaced to Shortcuts and can be
    completed later from the PETIT UI.
    """
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message must not be blank")

    session_id = (payload.session_id or "").strip() or DEFAULT_SESSION_ID
    request_id = f"ios_{uuid4().hex}"

    # Late import avoids a circular import while keeping /api/chat as the single
    # implementation of agent routing, persistence, and confirmation handling.
    from . import main as app_main  # noqa: PLC0415

    chat_result = app_main.chat(
        app_main.ChatRequest(
            message=message,
            request_id=request_id,
            session_id=session_id,
        )
    )
    pending_actions = [_model_dict(item) for item in chat_result.pending_actions]
    reply = str(chat_result.reply or "").strip()
    error = str(chat_result.error or "").strip() or None
    ok = error is None and bool(reply)

    log.info(
        "voice shortcut source=%s request_id=%s session_id=%s ok=%s pending_actions=%s",
        SOURCE,
        chat_result.request_id or request_id,
        session_id,
        ok,
        len(pending_actions),
    )
    return VoiceShortcutResponse(
        ok=ok,
        reply=reply,
        request_id=chat_result.request_id or request_id,
        needs_confirmation=bool(pending_actions),
        pending_actions=pending_actions,
        error=error,
    )
