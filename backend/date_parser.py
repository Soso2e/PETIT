"""Deterministic date parsing for schedule-related user messages."""
from __future__ import annotations

import re
from datetime import date, timedelta


_ISO_DATE_RE = re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")
_JP_FULL_DATE_RE = re.compile(r"(?<!\d)(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日")
_JP_MONTH_DAY_RE = re.compile(r"(?<!\d)(\d{1,2})月\s*(\d{1,2})日")


def _build_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_schedule_date(message: str, *, today: date | None = None) -> date | None:
    """Resolve an explicit schedule date from a Japanese user message.

    Supported forms:
    - 今日 / 明日 / 昨日
    - YYYY-MM-DD
    - YYYY年M月D日
    - M月D日 (interpreted in the current year)

    Returns ``None`` when the message contains no supported date or an invalid date.
    Ambiguous expressions such as weekdays or relative weeks are intentionally left
    unresolved so the caller can ask the user for confirmation.
    """
    base = today or date.today()
    text = message.strip()

    match = _ISO_DATE_RE.search(text)
    if match:
        return _build_date(*(int(value) for value in match.groups()))

    match = _JP_FULL_DATE_RE.search(text)
    if match:
        return _build_date(*(int(value) for value in match.groups()))

    match = _JP_MONTH_DAY_RE.search(text)
    if match:
        month, day = (int(value) for value in match.groups())
        return _build_date(base.year, month, day)

    if "明日" in text:
        return base + timedelta(days=1)
    if "昨日" in text:
        return base - timedelta(days=1)
    if "今日" in text:
        return base

    return None
