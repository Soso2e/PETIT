"""Runtime-local date and time context for PETIT prompts."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_DEFAULT_TIMEZONE = "Asia/Tokyo"
_WEEKDAYS_JA = ("月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日")


def timezone_name() -> str:
    """Return PETIT's configured IANA timezone name."""
    return os.getenv("PETIT_TIMEZONE", _DEFAULT_TIMEZONE).strip() or _DEFAULT_TIMEZONE


def local_zone() -> ZoneInfo:
    """Resolve PETIT's timezone, safely falling back to Asia/Tokyo."""
    try:
        return ZoneInfo(timezone_name())
    except ZoneInfoNotFoundError:
        return ZoneInfo(_DEFAULT_TIMEZONE)


def current_datetime(now: datetime | None = None) -> datetime:
    """Return an aware datetime in PETIT's local timezone."""
    zone = local_zone()
    if now is None:
        return datetime.now(zone)
    if now.tzinfo is None:
        return now.replace(tzinfo=zone)
    return now.astimezone(zone)


def snapshot(now: datetime | None = None) -> dict[str, Any]:
    """Return a compact runtime context suitable for APIs and tests."""
    value = current_datetime(now)
    return {
        "timezone": getattr(value.tzinfo, "key", timezone_name()),
        "current_datetime": value.isoformat(timespec="seconds"),
        "current_date": value.date().isoformat(),
        "weekday": _WEEKDAYS_JA[value.weekday()],
    }


def prompt_context(now: datetime | None = None) -> str:
    """Build the authoritative relative-date context injected into each turn."""
    value = snapshot(now)
    return (
        "現在日時コンテキスト（この情報を最優先）:\n"
        f"- タイムゾーン: {value['timezone']}\n"
        f"- 現在日時: {value['current_datetime']}\n"
        f"- 今日: {value['current_date']}（{value['weekday']}）\n"
        "- 『今日』『明日』『昨日』『今週』『今日まで』などの相対日付は、上記の現在日時を基準に解釈する。\n"
        "- モデルの学習時点や知識カットオフの日付を、現在日付として扱わない。"
    )


def with_current_context(base_prompt: str, now: datetime | None = None) -> str:
    """Append a fresh runtime clock to a stable system prompt."""
    return f"{str(base_prompt or '').rstrip()}\n\n{prompt_context(now)}"
