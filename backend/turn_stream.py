"""Ephemeral live progress for a running Turn.

This is display-only. The durable ledger (``turns`` / ``turn_events``) stays the
source of truth: a draft text shown here can be discarded (Tool round, Brain
fallback) and the final reply always comes from ``/api/chat`` or
``/api/turns/{request_id}``. Nothing here is persisted or used for approvals.
"""
from __future__ import annotations

import threading
import time
from typing import Any

MAX_TEXT_CHARS = 40_000
MAX_STREAMS = 64
RETAIN_SECONDS = 120.0

_lock = threading.Lock()
_streams: dict[str, dict[str, Any]] = {}


def _purge(now: float) -> None:
    for key in [k for k, v in _streams.items() if v["closed_at"] and now - v["closed_at"] > RETAIN_SECONDS]:
        _streams.pop(key, None)
    while len(_streams) >= MAX_STREAMS:
        # Oldest entry first; dict keeps insertion order.
        _streams.pop(next(iter(_streams)))


def open(request_id: str) -> None:  # noqa: A001 - module-level verb
    now = time.monotonic()
    with _lock:
        _purge(now)
        _streams[request_id] = {"phase": "thinking", "tool": None, "round": 0, "text": "",
                                "version": 1, "status": None, "closed_at": None}


def _update(request_id: str, **changes: Any) -> None:
    with _lock:
        stream = _streams.get(request_id)
        if stream is None or stream["closed_at"]:
            return  # Not watched (e.g. approval resume): updates are no-ops.
        stream.update(changes)
        stream["version"] += 1


def phase(request_id: str, name: str, *, tool: str | None = None, round: int | None = None) -> None:  # noqa: A002
    changes: dict[str, Any] = {"phase": name, "tool": tool}
    if round is not None:
        changes["round"] = round
    _update(request_id, **changes)


def delta(request_id: str, text: str) -> None:
    if not text:
        return
    with _lock:
        stream = _streams.get(request_id)
        if stream is None or stream["closed_at"] or len(stream["text"]) >= MAX_TEXT_CHARS:
            return
        stream["text"] = (stream["text"] + text)[:MAX_TEXT_CHARS]
        stream["phase"] = "replying"
        stream["tool"] = None
        stream["version"] += 1


def reset_text(request_id: str) -> None:
    """Discard a draft that turned out to be a Tool round or a failed Brain."""
    _update(request_id, text="")


def close(request_id: str, status: str | None) -> None:
    with _lock:
        stream = _streams.get(request_id)
        if stream is None:
            return
        stream["status"] = status or "unknown"
        stream["closed_at"] = time.monotonic()
        stream["version"] += 1


def snapshot(request_id: str) -> dict[str, Any] | None:
    with _lock:
        stream = _streams.get(request_id)
        if stream is None:
            return None
        return {k: stream[k] for k in ("phase", "tool", "round", "text", "version", "status")} | {
            "closed": bool(stream["closed_at"])}


def clear() -> None:
    """Test helper."""
    with _lock:
        _streams.clear()
