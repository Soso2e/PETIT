"""Runtime-local date and time context for PETIT prompts."""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_DEFAULT_TIMEZONE = "Asia/Tokyo"
_WEEKDAYS_JA = ("月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日")

_RELATIVE_DATE_PATTERN = re.compile(
    r"(?:今日|明日|明後日|昨日|一昨日|今夜|今朝|今週|来週|先週|今月|来月|先月|"
    r"今年|来年|去年|週末|月末|年末|期限|締切|までに|"
    r"(?:月|火|水|木|金|土|日)曜日|\d{1,2}月\d{1,2}日)"
)
_PRECISE_TIME_PATTERN = re.compile(
    r"(?:今何時|現在時刻|今から|あと\s*\d+\s*(?:分|時間)|"
    r"\d+\s*(?:分|時間)後|\d{1,2}\s*時(?:\s*\d{1,2}\s*分)?|何時|時刻)"
)


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
    """Build the full authoritative relative-date context."""
    value = snapshot(now)
    return (
        "実行時コンテキスト:\n"
        f"- タイムゾーン: {value['timezone']}\n"
        f"- 現在日時: {value['current_datetime']}\n"
        f"- 今日: {value['current_date']}（{value['weekday']}）\n"
        "- 相対日付はこの日時を基準に解釈する。\n"
        "- モデルの知識カットオフを現在日時として扱わない。"
    )


def _combined_text(
    text: str,
    history: list[dict[str, str]] | None = None,
) -> str:
    parts = [str(text or "")]
    for item in (history or [])[-2:]:
        if item.get("role") == "user":
            parts.append(str(item.get("content") or ""))
    return "\n".join(parts)


def needs_prompt_context(
    text: str,
    history: list[dict[str, str]] | None = None,
) -> bool:
    """Return whether the turn contains date or time expressions needing a clock."""
    combined = _combined_text(text, history)
    return bool(
        _RELATIVE_DATE_PATTERN.search(combined)
        or _PRECISE_TIME_PATTERN.search(combined)
    )


def prompt_context_for(
    text: str,
    *,
    history: list[dict[str, str]] | None = None,
    now: datetime | None = None,
) -> str:
    """Return only the clock precision needed by this turn.

    Date-only requests receive a day-stable context. Precise time expressions
    receive minute-level current time. The context is intended for a user turn,
    keeping the system prompt static for prefix reuse.
    """
    combined = _combined_text(text, history)
    if not needs_prompt_context(text, history):
        return ""

    value = current_datetime(now)
    timezone = getattr(value.tzinfo, "key", timezone_name())
    if _PRECISE_TIME_PATTERN.search(combined):
        return (
            "実行時コンテキスト:\n"
            f"- タイムゾーン: {timezone}\n"
            f"- 現在日時: {value.isoformat(timespec='minutes')}\n"
            "- 相対日時はこの時刻を基準に解釈する。"
        )

    return (
        "実行時コンテキスト:\n"
        f"- タイムゾーン: {timezone}\n"
        f"- 今日: {value.date().isoformat()}（{_WEEKDAYS_JA[value.weekday()]}）\n"
        "- 相対日付はこの日付を基準に解釈する。"
    )


def with_current_context(base_prompt: str, now: datetime | None = None) -> str:
    """Compatibility helper for callers that still need full prompt injection."""
    return f"{str(base_prompt or '').rstrip()}\n\n{prompt_context(now)}"
