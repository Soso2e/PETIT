"""Per-request identifiers shared with tools without expanding tool schemas."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_request_id: ContextVar[str | None] = ContextVar("petit_request_id", default=None)
_session_id: ContextVar[str | None] = ContextVar("petit_session_id", default=None)


@contextmanager
def bind(*, request_id: str | None, session_id: str | None) -> Iterator[None]:
    request_token = _request_id.set(request_id)
    session_token = _session_id.set(session_id)
    try:
        yield
    finally:
        _request_id.reset(request_token)
        _session_id.reset(session_token)


def current_ids() -> tuple[str | None, str | None]:
    """Return ``(request_id, session_id)`` for the active chat request."""
    return _request_id.get(), _session_id.get()
