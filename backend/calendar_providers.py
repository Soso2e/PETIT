"""Calendar write-provider boundary.

ICS remains a read-only import in ``calendar_sync``. New write adapters (for
example Google Calendar OAuth) can register here without changing the agent
tool contract.
"""
from __future__ import annotations

from typing import Any, Callable

from . import db

Provider = Callable[..., dict[str, Any]]
_PROVIDERS: dict[str, Provider] = {}


def register(name: str, provider: Provider) -> None:
    _PROVIDERS[name] = provider


def available() -> list[str]:
    return sorted(_PROVIDERS)


def add_event(destination: str = "local", **event: Any) -> dict[str, Any]:
    provider = _PROVIDERS.get(destination)
    if provider is None:
        return {
            "added": False,
            "destination": destination,
            "error": f"予定の書き込み先 '{destination}' は未設定です。利用可能: {', '.join(available())}",
        }
    return provider(**event)


def _add_local(
    title: str,
    start_time: str,
    end_time: str | None = None,
    location: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    with db.get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO calendar_events_cache "
            "(source, title, start_time, end_time, location, description, updated_at) "
            "VALUES ('local', ?, ?, ?, ?, ?, ?)",
            (title, start_time, end_time, location, description, db.now_iso()),
        )
        event_id = int(cur.lastrowid)
    return {
        "added": True,
        "destination": "local",
        "id": event_id,
        "title": title,
        "start_time": start_time,
        "end_time": end_time,
        "location": location,
        "description": description,
    }


register("local", _add_local)
