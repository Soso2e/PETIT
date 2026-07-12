"""Current date/time tools."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone as fixed_timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .registry import tool

WEEKDAYS_JA = ["月", "火", "水", "木", "金", "土", "日"]

TIMEZONE_FALLBACKS = {
    "UTC": fixed_timezone.utc,
    "Asia/Tokyo": fixed_timezone(timedelta(hours=9), "Asia/Tokyo"),
}


@tool(
    name="get_current_time",
    description=(
        "現在の日付・時刻を取得する。"
        "『今何時？』『今日何日？』『今の時間』のように現在時刻や日付を聞かれたら使う。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "timezone": {
                "type": "string",
                "description": "IANA timezone。例: Asia/Tokyo, UTC。省略時は実行環境のローカル時刻。",
            },
        },
    },
)
def get_current_time(timezone: str | None = None) -> dict[str, Any]:
    tz_name = (timezone or "").strip()
    if tz_name:
        try:
            now = datetime.now(ZoneInfo(tz_name))
        except ZoneInfoNotFoundError:
            fallback = TIMEZONE_FALLBACKS.get(tz_name)
            if fallback is None:
                return {"ok": False, "error": f"unknown timezone: {tz_name}"}
            now = datetime.now(fallback)
    else:
        now = datetime.now().astimezone()

    return {
        "ok": True,
        "iso": now.isoformat(timespec="seconds"),
        "date": now.date().isoformat(),
        "time": now.strftime("%H:%M:%S"),
        "weekday": WEEKDAYS_JA[now.weekday()],
        "timezone": getattr(now.tzinfo, "key", None) or now.tzname(),
        "utc_offset": now.strftime("%z"),
    }
