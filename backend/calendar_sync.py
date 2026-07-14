"""Safe, read-only synchronization for Google/local ICS and TimeTree."""
from __future__ import annotations

import hashlib
import logging
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable

from . import config, db
from .calendar_sources import timetree

log = logging.getLogger(__name__)
TOKYO = timezone(timedelta(hours=9), name="Asia/Tokyo")
_last_sync_monotonic: float | None = None
_last_result: dict[str, Any] | None = None


def configured() -> bool:
    return bool(config.CALENDAR_ICS_URLS or config.CALENDAR_ICS_FILES or timetree.configured())


def _result(source: str, ok: bool, count: int = 0, cached: bool = False, error: str | None = None) -> dict[str, Any]:
    state = db.sync_state(source)
    with db.get_connection() as conn:
        has_cache = bool(conn.execute("SELECT 1 FROM calendar_events_cache WHERE source_key = ? LIMIT 1", (source,)).fetchone())
    return {"ok": ok, "source": source, "synced_count": count, "cached": bool(cached or (not ok and has_cache)),
            "stale": bool(not ok and state["last_success_at"]), "last_synced_at": state["last_success_at"],
            "error": error}


def status() -> dict[str, Any]:
    states = []
    for state in db.all_sync_states():
        states.append({"source": state["source"], "last_synced_at": state["last_success_at"],
                       "last_failed_at": state["last_failure_at"], "synced_count": state["synced_count"],
                       "error": state["last_error"], "stale": bool(state["last_failure_at"] and state["last_success_at"])})
    return {"configured": configured(), "url_count": len(config.CALENDAR_ICS_URLS),
            "file_count": len(config.CALENDAR_ICS_FILES), "timetree_configured": timetree.configured(),
            "sync_states": states}


def sync_if_configured(force: bool = False) -> dict[str, Any]:
    global _last_sync_monotonic, _last_result
    if not configured():
        return {**_result("calendar", False, error="外部カレンダーが設定されていません"), "configured": False, "sources": []}
    if not force and _last_sync_monotonic is not None and _last_result is not None and time.monotonic() - _last_sync_monotonic < config.CALENDAR_SYNC_TTL_SECONDS:
        return {**_last_result, "cached": True}
    result = sync()
    _last_sync_monotonic, _last_result = time.monotonic(), result
    return result


def sync() -> dict[str, Any]:
    specs: list[tuple[str, str, Callable[[], str]]] = []
    specs += [(f"google_ics:{i}", "google_ics", lambda url=url: _read_url(url)) for i, url in enumerate(config.CALENDAR_ICS_URLS, 1)]
    specs += [(f"local_ics:{i}", "ics_file", lambda path=path: _read_file(path)) for i, path in enumerate(config.CALENDAR_ICS_FILES, 1)]
    if timetree.configured():
        specs.append(("timetree", "timetree", timetree.fetch_ics))

    results: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str | None]] = set()
    for source_key, public_source, fetch in specs:
        try:
            events = parse_ics(fetch())
            unique = []
            for event in events:
                identity = (event["title"], event["start_time"], event.get("end_time"))
                if identity not in seen:
                    seen.add(identity)
                    unique.append(event)
            _replace_source(source_key, public_source, unique)
            at = db.record_sync_success(source_key, len(unique))
            results.append({"ok": True, "source": public_source, "synced_count": len(unique), "cached": False,
                            "stale": False, "last_synced_at": at, "error": None})
        except Exception as exc:  # no exception content: it can contain a private URL or credential
            error = _safe_error(public_source, exc)
            db.record_sync_failure(source_key, error)
            results.append(_result(source_key, False, error=error) | {"source": public_source})
            log.warning("calendar source sync failed: %s", public_source)
    total = sum(item["synced_count"] for item in results if item["ok"])
    ok = bool(results) and any(item["ok"] for item in results)
    error = None if ok else (results[0]["error"] if results else "外部カレンダーが設定されていません")
    return {"ok": ok, "source": "calendar", "synced_count": total, "cached": False,
            "stale": any(item["stale"] for item in results), "last_synced_at": db.now_iso() if ok else None,
            "error": error, "configured": bool(specs), "sources": results, "synced": total}


def _replace_source(source_key: str, source: str, events: list[dict[str, Any]]) -> None:
    now = db.now_iso()
    with db.get_connection() as conn:
        conn.execute("DELETE FROM calendar_events_cache WHERE source_key = ?", (source_key,))
        for event in events:
            external_id = event.get("external_id") or hashlib.sha256(
                f"{event['title']}|{event['start_time']}|{event.get('end_time') or ''}".encode()).hexdigest()
            conn.execute("INSERT INTO calendar_events_cache (source, source_key, external_id, title, start_time, end_time, location, description, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (source, source_key, external_id, event["title"], event["start_time"], event.get("end_time"), event.get("location"), event.get("description"), now))


def parse_ics(text: str) -> list[dict[str, Any]]:
    events, current = [], None
    for raw_line in _unfold_lines(text):
        line = raw_line.strip()
        if line == "BEGIN:VEVENT": current = {}; continue
        if line == "END:VEVENT":
            if current:
                event = _event_from_props(current)
                if event: events.append(event)
            current = None; continue
        if current is not None and ":" in line:
            key, value = line.split(":", 1); name = key.split(";", 1)[0].upper()
            if name not in current: current[name] = _unescape(value)
    return events


def _event_from_props(props: dict[str, str]) -> dict[str, Any] | None:
    title, start = props.get("SUMMARY", "").strip(), _normalize_ical_datetime(props.get("DTSTART"))
    if not title or not start: return None
    return {"external_id": props.get("UID") or None, "title": title, "start_time": start,
            "end_time": _normalize_ical_datetime(props.get("DTEND")), "location": props.get("LOCATION") or None,
            "description": props.get("DESCRIPTION") or None}


def _read_url(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "PETIT/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
        return response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")


def _read_file(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _unfold_lines(text: str) -> list[str]:
    lines = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw.startswith((" ", "\t")) and lines: lines[-1] += raw[1:]
        else: lines.append(raw)
    return lines


def _normalize_ical_datetime(value: str | None) -> str | None:
    if not value: return None
    value = value.strip()
    if len(value) == 8 and value.isdigit(): return f"{value[:4]}-{value[4:6]}-{value[6:8]}"
    if value.endswith("Z"): value = value[:-1] + "+0000"
    try: return datetime.strptime(value, "%Y%m%dT%H%M%S%z").isoformat(timespec="seconds")
    except ValueError: pass
    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M"):
        try: return datetime.strptime(value, fmt).replace(tzinfo=TOKYO).isoformat(timespec="seconds")
        except ValueError: pass
    try: return parsedate_to_datetime(value).isoformat(timespec="seconds")
    except (TypeError, ValueError): return None


def _unescape(value: str) -> str:
    return value.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\").strip()


def _safe_error(source: str, exc: Exception) -> str:
    if source == "timetree": return "TimeTree の同期に失敗しました"
    if isinstance(exc, FileNotFoundError): return "ICS ファイルが見つかりません"
    return "カレンダーの取得または解析に失敗しました"
