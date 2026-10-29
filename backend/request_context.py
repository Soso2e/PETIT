"""Per-request identifiers shared with tools without expanding tool schemas."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_request_id: ContextVar[str | None] = ContextVar("petit_request_id", default=None)
_conversation_mode: ContextVar[str] = ContextVar("petit_conversation_mode", default="text")
_session_id: ContextVar[str | None] = ContextVar("petit_session_id", default=None)
_is_admin: ContextVar[bool] = ContextVar("petit_is_admin", default=False)


@contextmanager
def bind(*, request_id: str | None, session_id: str | None, conversation_mode: str = "text",
         is_admin: bool = False) -> Iterator[None]:
    request_token = _request_id.set(request_id)
    session_token = _session_id.set(session_id)
    mode_token = _conversation_mode.set(conversation_mode)
    admin_token = _is_admin.set(is_admin)
    try:
        yield
    finally:
        _request_id.reset(request_token)
        _session_id.reset(session_token)
        _conversation_mode.reset(mode_token)
        _is_admin.reset(admin_token)


def current_ids() -> tuple[str | None, str | None]:
    """Return ``(request_id, session_id)`` for the active chat request."""
    return _request_id.get(), _session_id.get()


def current_conversation_mode() -> str:
    return _conversation_mode.get()


def current_is_admin() -> bool:
    return _is_admin.get()


def local_only() -> bool:
    """Read the current Thread's disclosure mode without creating any schema."""
    _request_id, session_id = current_ids()
    if not session_id:
        return False
    from pathlib import Path
    from . import config, db
    if not Path(config.DB_PATH).exists():
        return False
    with db.get_connection() as connection:
        if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='threads'").fetchone():
            return False
        row = connection.execute("SELECT privacy FROM threads WHERE id=?", (session_id,)).fetchone()
    return bool(row and row["privacy"] == "local_only")
