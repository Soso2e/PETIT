"""Track and summarize daily DeepSeek API token usage and estimated USD cost."""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any
from zoneinfo import ZoneInfo

from . import config, db, request_context

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS deepseek_usage_log (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at               TEXT NOT NULL,
    day_key                  TEXT NOT NULL,
    model                    TEXT NOT NULL,
    route                    TEXT NOT NULL DEFAULT '',
    prompt_tokens            INTEGER NOT NULL DEFAULT 0,
    prompt_cache_hit_tokens  INTEGER NOT NULL DEFAULT 0,
    prompt_cache_miss_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens        INTEGER NOT NULL DEFAULT 0,
    cost_usd                 REAL NOT NULL DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS idx_deepseek_usage_day ON deepseek_usage_log(day_key);
"""

# USD per 1M tokens: (cache_hit, cache_miss, output)
_RATES_OFF_PEAK = {
    "flash": (0.003, 0.15, 0.60),
    "pro": (0.022, 0.66, 1.98),
}
_RATES_PEAK = {
    "flash": (0.006, 0.30, 1.20),
    "pro": (0.044, 1.32, 3.96),
}


def ensure_schema(conn=None) -> None:
    if conn is not None:
        conn.executescript(SCHEMA)
        return
    with db.get_connection() as connection:
        connection.executescript(SCHEMA)


def _today_key(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    return current.astimezone(ZoneInfo(config.DAILY_INDEX_TIMEZONE)).date().isoformat()


def is_peak_utc(now: datetime | None = None) -> bool:
    """DeepSeek peak hours: 01:00-04:00 and 06:00-10:00 UTC, Mon-Fri."""
    utc_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if utc_now.weekday() >= 5:
        return False
    return utc_now.hour in {1, 2, 3, 6, 7, 8, 9}


def _rate_tier(model: str) -> str:
    return "pro" if "pro" in (model or "").lower() else "flash"


def _non_negative_int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def calculate_cost_usd(
    usage: dict[str, Any] | None,
    *,
    model: str = "",
    now: datetime | None = None,
) -> float:
    if not isinstance(usage, dict):
        return 0.0
    prompt_tokens = _non_negative_int(usage.get("prompt_tokens"))
    cache_hit = _non_negative_int(usage.get("prompt_cache_hit_tokens"))
    raw_miss = usage.get("prompt_cache_miss_tokens")
    if isinstance(raw_miss, int) and not isinstance(raw_miss, bool) and raw_miss >= 0:
        cache_miss = raw_miss
    else:
        cache_miss = max(0, prompt_tokens - cache_hit)
    completion_tokens = _non_negative_int(usage.get("completion_tokens"))

    rates = (_RATES_PEAK if is_peak_utc(now) else _RATES_OFF_PEAK)[_rate_tier(model)]
    return (
        cache_hit * rates[0]
        + cache_miss * rates[1]
        + completion_tokens * rates[2]
    ) / 1_000_000.0


def record(
    usage: dict[str, Any] | None,
    *,
    model: str = "",
    route: str = "",
    now: datetime | None = None,
) -> None:
    """Best-effort persistence of a single DeepSeek completion's token usage and cost."""
    if not isinstance(usage, dict) or not usage:
        return
    if request_context.is_guild_mode():
        return
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    prompt_tokens = _non_negative_int(usage.get("prompt_tokens"))
    cache_hit = _non_negative_int(usage.get("prompt_cache_hit_tokens"))
    raw_miss = usage.get("prompt_cache_miss_tokens")
    cache_miss = (
        raw_miss
        if isinstance(raw_miss, int) and not isinstance(raw_miss, bool) and raw_miss >= 0
        else max(0, prompt_tokens - cache_hit)
    )
    completion_tokens = _non_negative_int(usage.get("completion_tokens"))
    cost_usd = calculate_cost_usd(usage, model=model, now=current)
    try:
        with db.get_connection() as conn:
            ensure_schema(conn)
            conn.execute(
                "INSERT INTO deepseek_usage_log("
                "created_at, day_key, model, route, prompt_tokens, "
                "prompt_cache_hit_tokens, prompt_cache_miss_tokens, completion_tokens, cost_usd"
                ") VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    current.isoformat(timespec="seconds"),
                    _today_key(current),
                    str(model or ""),
                    str(route or ""),
                    prompt_tokens,
                    cache_hit,
                    cache_miss,
                    completion_tokens,
                    cost_usd,
                ),
            )
    except Exception:  # noqa: BLE001 - usage telemetry must never break chat/background flows
        log.debug("failed to record deepseek usage", exc_info=True)


def today_summary(*, now: datetime | None = None) -> dict[str, Any]:
    day_key = _today_key(now)
    with db.get_connection() as conn:
        ensure_schema(conn)
        row = conn.execute(
            "SELECT COUNT(*) AS requests, COALESCE(SUM(cost_usd), 0.0) AS cost_usd, "
            "COALESCE(SUM(prompt_tokens + completion_tokens), 0) AS tokens "
            "FROM deepseek_usage_log WHERE day_key=?",
            (day_key,),
        ).fetchone()
    return {
        "day": day_key,
        "cost_usd": round(float(row["cost_usd"] or 0.0), 6),
        "requests": int(row["requests"] or 0),
        "tokens": int(row["tokens"] or 0),
    }
