"""Ephemeral in-memory streaming buffer for live coding job progress and CLI output."""
from __future__ import annotations

from contextlib import contextmanager
import threading
import time

MAX_DRAFT_CHARS = 16000
_LOCK = threading.Lock()
_STREAMS: dict[str, dict] = {}
_LOCAL = threading.local()


@contextmanager
def bind(job_id: str):
    previous = getattr(_LOCAL, "job_id", None)
    _LOCAL.job_id = job_id
    try:
        yield
    finally:
        _LOCAL.job_id = previous


def append_delta_current(text: str) -> None:
    job_id = getattr(_LOCAL, "job_id", None)
    if job_id:
        append_delta(job_id, text)


def append_thought_current(text: str) -> None:
    job_id = getattr(_LOCAL, "job_id", None)
    if job_id:
        append_thought(job_id, text)


def add_activity_current(text: str) -> None:
    job_id = getattr(_LOCAL, "job_id", None)
    if job_id:
        add_activity(job_id, text)


def publish_tool_current(tool_name: str) -> None:
    job_id = getattr(_LOCAL, "job_id", None)
    if job_id:
        publish_tool(job_id, tool_name)


def _entry(job_id: str) -> dict:
    item = _STREAMS.get(job_id)
    if item is None:
        item = {"seq": 0, "draft": "", "thought": "", "tool": "", "activity": [], "updated_at": time.monotonic()}
        _STREAMS[job_id] = item
    return item


def append_delta(job_id: str, text: str) -> None:
    if not job_id or not isinstance(text, str) or not text:
        return
    with _LOCK:
        item = _entry(job_id)
        item["draft"] = (item["draft"] + text)[-MAX_DRAFT_CHARS:]
        item["tool"] = ""
        item["seq"] += 1
        item["updated_at"] = time.monotonic()


def append_thought(job_id: str, text: str) -> None:
    if not job_id or not isinstance(text, str) or not text:
        return
    with _LOCK:
        item = _entry(job_id)
        item["thought"] = (item["thought"] + text)[-MAX_DRAFT_CHARS:]
        item["seq"] += 1
        item["updated_at"] = time.monotonic()


def add_activity(job_id: str, text: str) -> None:
    if not job_id or not isinstance(text, str) or not text.strip():
        return
    with _LOCK:
        item = _entry(job_id)
        item["activity"] = (item["activity"] + [text.strip()[:300]])[-20:]
        item["seq"] += 1
        item["updated_at"] = time.monotonic()


def publish_tool(job_id: str, tool_name: str) -> None:
    if not job_id or not isinstance(tool_name, str) or not tool_name:
        return
    with _LOCK:
        item = _entry(job_id)
        item["tool"] = tool_name[:120]
        item["seq"] += 1
        item["updated_at"] = time.monotonic()


def snapshot(job_id: str) -> dict:
    with _LOCK:
        item = _STREAMS.get(job_id)
        if not item:
            return {"seq": 0, "draft": "", "thought": "", "tool": "", "activity": []}
        return {
            "seq": item["seq"],
            "draft": item["draft"],
            "thought": item["thought"],
            "tool": item["tool"],
            "activity": list(item["activity"]),
        }


def clear(job_id: str) -> None:
    with _LOCK:
        _STREAMS.pop(job_id, None)
