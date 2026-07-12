"""Read-only calendar sync adapters.

The first supported source is iCalendar/ICS, which works with Google Calendar's
private iCal export URL and with local exported .ics files. Events are normalized
into calendar_events_cache so existing schedule and briefing paths can read them.
"""
from __future__ import annotations

import logging
import time
import urllib.request
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from . import config, db

log = logging.getLogger(__name__)

_last_sync_monotonic: float | None = None
_last_result: dict[str, Any] | None = None


def configured() -> bool:
    return bool(config.CALENDAR_ICS_URLS or config.CALENDAR_ICS_FILES)


def status() -> dict[str, Any]:
    return {
        "provider": "ics" if configured() else "local_cache",
        "configured": configured(),
        "url_count": len(config.CALENDAR_ICS_URLS),
        "file_count": len(config.CALENDAR_ICS_FILES),
        "last_sync": _last_result,
    }


def sync_if_configured(force: bool = False) -> dict[str, Any]:
    """Refresh calendar cache when sources are configured.

    Uses a lightweight in-process TTL to avoid fetching private calendar URLs on
    every planning turn.
    """
    global _last_sync_monotonic, _last_result

    if not configured():
        return {"synced": 0, "configured": False, "source": "local_cache"}

    now = time.monotonic()
    if (
        not force
        and _last_sync_monotonic is not None
        and _last_result is not None
        and now - _last_sync_monotonic < config.CALENDAR_SYNC_TTL_SECONDS
    ):
        return {**_last_result, "cached": True}

    result = sync()
    _last_sync_monotonic = now
    _last_result = result
    return result


def sync() -> dict[str, Any]:
    sources: list[tuple[str, str, str]] = []
    errors: list[dict[str, str]] = []

    for idx, url in enumerate(config.CALENDAR_ICS_URLS, start=1):
        try:
            sources.append((f"url:{idx}", url, _read_url(url)))
        except Exception as exc:  # noqa: BLE001
            errors.append({"source": f"url:{idx}", "error": type(exc).__name__})
            log.debug("calendar url sync failed (%s): %s", url, exc)

    for path in config.CALENDAR_ICS_FILES:
        try:
            sources.append((f"file:{path}", str(path), _read_file(path)))
        except Exception as exc:  # noqa: BLE001
            errors.append({"source": f"file:{path}", "error": type(exc).__name__})
            log.debug("calendar file sync failed (%s): %s", path, exc)

    events: list[dict[str, Any]] = []
    for source_id, source_label, text in sources:
        for event in parse_ics(text):
            event["source"] = "google_ics" if source_id.startswith("url:") else "ics_file"
            event["description"] = _with_source(event.get("description"), source_label)
            events.append(event)

    conn = db.get_connection()
    try:
        conn.execute("DELETE FROM calendar_events_cache WHERE source IN ('google_ics', 'ics_file')")
        for event in events:
            conn.execute(
                "INSERT INTO calendar_events_cache "
                "(source, title, start_time, end_time, location, description, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    event["source"],
                    event["title"],
                    event.get("start_time"),
                    event.get("end_time"),
                    event.get("location"),
                    event.get("description"),
                    db.now_iso(),
                ),
            )
        conn.commit()
    finally:
        conn.close()

    return {
        "synced": len(events),
        "configured": True,
        "sources": len(sources),
        "errors": errors,
    }


def parse_ics(text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    current: dict[str, str] | None = None

    for raw_line in _unfold_lines(text):
        line = raw_line.strip()
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current:
                event = _event_from_props(current)
                if event:
                    events.append(event)
            current = None
            continue
        if current is None or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key_name = key.split(";", 1)[0].upper()
        if key_name not in current:
            current[key_name] = _unescape(value)

    return events


def _event_from_props(props: dict[str, str]) -> dict[str, Any] | None:
    title = props.get("SUMMARY", "").strip()
    start = _normalize_ical_datetime(props.get("DTSTART"))
    if not title or not start:
        return None
    return {
        "title": title,
        "start_time": start,
        "end_time": _normalize_ical_datetime(props.get("DTEND")),
        "location": props.get("LOCATION") or None,
        "description": props.get("DESCRIPTION") or None,
    }


def _read_url(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "PETIT/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
        content_type = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(content_type, errors="replace")


def _read_file(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _unfold_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _normalize_ical_datetime(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:8]}"
    if value.endswith("Z"):
        value = value[:-1] + "+0000"
    try:
        parsed = datetime.strptime(value, "%Y%m%dT%H%M%S%z")
        return parsed.isoformat(timespec="seconds")
    except ValueError:
        pass
    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M"):
        try:
            return datetime.strptime(value, fmt).isoformat(timespec="seconds")
        except ValueError:
            pass
    try:
        return parsedate_to_datetime(value).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return value


def _unescape(value: str) -> str:
    return (
        value.replace("\\n", "\n")
        .replace("\\N", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
        .strip()
    )


def _with_source(description: str | None, source_label: str) -> str:
    source_line = f"calendar_source={source_label}"
    if description:
        return f"{description}\n{source_line}"
    return source_line
