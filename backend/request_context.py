"""Per-request identifiers shared with tools without expanding tool schemas."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_request_id: ContextVar[str | None] = ContextVar("petit_request_id", default=None)
_conversation_mode: ContextVar[str] = ContextVar("petit_conversation_mode", default="text")
_session_id: ContextVar[str | None] = ContextVar("petit_session_id", default=None)


@contextmanager
def bind(*, request_id: str | None, session_id: str | None, conversation_mode: str = "text") -> Iterator[None]:
    request_token = _request_id.set(request_id)
    session_token = _session_id.set(session_id)
    mode_token = _conversation_mode.set(conversation_mode)
    try:
        yield
    finally:
        _request_id.reset(request_token)
        _session_id.reset(session_token)
        _conversation_mode.reset(mode_token)


def current_ids() -> tuple[str | None, str | None]:
    """Return ``(request_id, session_id)`` for the active chat request."""
    return _request_id.get(), _session_id.get()


def current_conversation_mode() -> str:
    return _conversation_mode.get()
