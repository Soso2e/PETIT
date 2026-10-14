"""Current date/time tools."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone as fixed_timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .. import time_context
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
        "通常はユーザーの基本タイムゾーン（Asia/Tokyo）の時刻を返す。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "timezone": {
                "type": "string",
                "description": "特定の地域や国の時刻を明示的に聞かれた場合のみ指定するIANA timezone（例: America/New_York）。普段の時刻確認では指定不要（PETITの基本タイムゾーンAsia/Tokyoで取得される）。",
            },
        },
    },
)
def get_current_time(timezone: str | None = None) -> dict[str, Any]:
    tz_name = (timezone or "").strip()
    if tz_name and tz_name.lower() not in {"default", "local", "asia/tokyo", "jst"}:
        try:
            now = datetime.now(ZoneInfo(tz_name))
        except ZoneInfoNotFoundError:
            fallback = TIMEZONE_FALLBACKS.get(tz_name)
            if fallback is None:
                return {"ok": False, "error": f"unknown timezone: {tz_name}"}
            now = datetime.now(fallback)
    else:
        now = time_context.current_datetime()

    return {
        "ok": True,
        "iso": now.isoformat(timespec="seconds"),
        "date": now.date().isoformat(),
        "time": now.strftime("%H:%M:%S"),
        "weekday": WEEKDAYS_JA[now.weekday()],
        "timezone": getattr(now.tzinfo, "key", None) or now.tzname() or time_context.timezone_name(),
        "utc_offset": now.strftime("%z"),
    }
