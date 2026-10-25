"""Persistent 02:00 JST pull scheduling, atomic deltas, and operational alerts."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import threading
import time
from uuid import uuid4

from . import db, setup_store as settings, google_services

JST = timezone(timedelta(hours=9))
_stop = threading.Event()
_thread = None
SCHEMA = """
CREATE TABLE IF NOT EXISTS service_sync_state (
 service TEXT PRIMARY KEY, slot TEXT, lease TEXT, lease_until REAL NOT NULL DEFAULT 0,
 last_success TEXT, last_failure TEXT, error TEXT, updated_count INTEGER NOT NULL DEFAULT 0,
 cursor TEXT, identity TEXT, next_attempt REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS service_event_versions (
 source_key TEXT NOT NULL, external_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
 remote_updated TEXT, PRIMARY KEY(source_key,external_id));
CREATE TABLE IF NOT EXISTS service_alerts (
 service TEXT PRIMARY KEY, first_failure TEXT NOT NULL, last_failure TEXT NOT NULL,
 error TEXT NOT NULL, resolved_at TEXT, notified_at TEXT, notification_id INTEGER);
"""
LABELS = {"google_calendar": "Googleカレンダー", "timetree": "TimeTree", "notion": "Notion"}


def ensure_schema():
    with db.get_connection() as c:
        c.executescript(SCHEMA)


def status() -> dict:
    ensure_schema()
    with db.get_connection() as c:
        states = [dict(x) for x in c.execute("SELECT service,slot,last_success,last_failure,error,updated_count,lease_until FROM service_sync_state")]
        alerts = [dict(x) for x in c.execute("SELECT * FROM service_alerts WHERE resolved_at IS NULL")]
    return {"states": states, "alerts": alerts, "schedule": "02:00 Asia/Tokyo", "direction": "read_only"}


def warning() -> str:
    # Avoid schema mutation inside a Tool effect transaction.
    with db.get_connection() as c:
        exists = c.execute("SELECT 1 FROM sqlite_master WHERE name='service_alerts'").fetchone()
        rows = list(c.execute("SELECT service FROM service_alerts WHERE resolved_at IS NULL ORDER BY service")) if exists else []
    if not rows:
        return ""
    names = "・".join(LABELS.get(x["service"], x["service"]) for x in rows)
    return f"ちなみに、{names}の同期が失敗しているよ。情報が最新ではない可能性がある。設定から再試行できるよ。"


def fail(service: str, error: str):
    ensure_schema()
    now = db.now_iso()
    with db.write_transaction() as c:
        c.execute("INSERT INTO service_alerts(service,first_failure,last_failure,error) VALUES(?,?,?,?) "
                  "ON CONFLICT(service) DO UPDATE SET last_failure=excluded.last_failure,error=excluded.error,"
                  "first_failure=CASE WHEN resolved_at IS NOT NULL THEN excluded.first_failure ELSE first_failure END,"
                  "notified_at=CASE WHEN resolved_at IS NOT NULL THEN NULL ELSE notified_at END, resolved_at=NULL",
                  (service, now, now, error))
        # Claim before delivery. A delivery crash never causes duplicate Push on each poll.
        claimed = c.execute("UPDATE service_alerts SET notified_at=? WHERE service=? AND notified_at IS NULL", (now, service)).rowcount
    if not claimed:
        return
    try:
        from . import notifications
        result = notifications.dispatch_notification(category="sync_failure", title="同期失敗: " + LABELS.get(service, service),
                    body=error, url="/static/setup.html#alerts", respect_preferences=True)
        with db.get_connection() as c:
            c.execute("UPDATE service_alerts SET notification_id=? WHERE service=? AND notified_at=?", (result["event_id"], service, now))
    except Exception:
        pass  # alert was persisted before notification; delivery cannot erase it


def resolve(service: str, c=None):
    if c is None:
        with db.write_transaction() as connection:
            resolve(service, connection)
        return
    c.execute("UPDATE service_alerts SET resolved_at=? WHERE service=? AND resolved_at IS NULL", (db.now_iso(), service))
    if c.execute("SELECT 1 FROM sqlite_master WHERE name='notification_events'").fetchone():
        columns = {x["name"] for x in c.execute("PRAGMA table_info(notification_events)")}
        if "resolved_at" in columns:
            c.execute("UPDATE notification_events SET resolved_at=CURRENT_TIMESTAMP WHERE id IN "
                      "(SELECT notification_id FROM service_alerts WHERE service=?)", (service,))


def _time(value: dict) -> str:
    if value.get("date"):
        return value["date"]
    parsed = datetime.fromisoformat(value["dateTime"].replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        from zoneinfo import ZoneInfo
        parsed = parsed.replace(tzinfo=ZoneInfo(value.get("timeZone", "Asia/Tokyo")))
    return parsed.astimezone(JST).isoformat(timespec="seconds")


def _fetch(service, data, state):
    if service == "google_calendar":
        identity = data["google_calendar_id"]
        items, cursor, full = google_services.calendar_changes(identity, state.get("cursor") if state.get("identity") == identity else None)
        events = []
        for item in items:
            if item.get("status") == "cancelled":
                events.append({"external_id": item["id"], "deleted": True})
            else:
                events.append({"external_id": item["id"], "title": item.get("summary", "（無題）"),
                               "start_time": _time(item["start"]), "end_time": _time(item["end"]),
                               "location": item.get("location"), "description": item.get("description"),
                               "remote_updated": item.get("updated"), "etag": item.get("etag")})
        return events, cursor, full, identity
    from .calendar_sources import timetree
    from .calendar_sync import parse_ics
    text = timetree.fetch_ics()
    if "BEGIN:VCALENDAR" not in text or "END:VCALENDAR" not in text or text.count("BEGIN:VEVENT") != text.count("END:VEVENT"):
        raise google_services.ServiceError("invalid_calendar_response")
    events = parse_ics(text)
    if len(events) != text.count("BEGIN:VEVENT"):
        raise google_services.ServiceError("incomplete_calendar_response")
    # An unexpected empty TimeTree export must not erase an existing good snapshot.
    if not events:
        with db.get_connection() as c:
            if c.execute("SELECT 1 FROM calendar_events_cache WHERE source_key LIKE 'setup:timetree:%'").fetchone():
                raise google_services.ServiceError("unexpected_empty_snapshot")
    return events, None, True, data["secrets"].get("timetree_calendar", "")


def source_key(data=None) -> str | None:
    data = data or settings.load()
    service = data["calendar"]
    if service == "local":
        return None
    identity = data["google_calendar_id"] if service == "google_calendar" else data["secrets"].get("timetree_calendar", "")
    return f"setup:{service}:" + hashlib.sha256(identity.encode()).hexdigest()[:24]


def cache_filter() -> tuple[str, tuple]:
    if not settings.initialized():
        return "", ()
    return "(source='local' OR source_key=?)", (source_key(),)


def sync(service: str | None = None, *, manual=False, now: datetime | None = None) -> dict:
    data = settings.load()
    service = service or data["calendar"]
    if service == "local":
        return {"ok": True, "local": True, "updated_count": 0}
    if service not in {"google_calendar", "timetree"} or service not in data["connected"] or service != data["calendar"]:
        raise ValueError("アクティブな接続済みカレンダーを選択してください。")
    ensure_schema()
    instant = now or datetime.now(JST)
    local = instant.astimezone(JST)
    slot = (local - timedelta(days=1) if local.hour < 2 else local).date().isoformat()
    lease = uuid4().hex
    with db.write_transaction() as c:
        c.execute("INSERT OR IGNORE INTO service_sync_state(service) VALUES(?)", (service,))
        state = dict(c.execute("SELECT * FROM service_sync_state WHERE service=?", (service,)).fetchone())
        if state["lease_until"] > time.time():
            return {"ok": False, "busy": True}
        identity = data["google_calendar_id"] if service == "google_calendar" else data["secrets"].get("timetree_calendar", "")
        if not manual and ((state["slot"] == slot and state["identity"] == identity) or state["next_attempt"] > time.time()):
            return {"ok": True, "skipped": True}
        c.execute("UPDATE service_sync_state SET lease=?,lease_until=? WHERE service=?", (lease, time.time()+600, service))
    try:
        events, cursor, full, identity = _fetch(service, data, state)
        key, changed = source_key(data), 0
        with db.write_transaction() as c:
            live = settings.load()
            owner = c.execute("SELECT lease,lease_until FROM service_sync_state WHERE service=?", (service,)).fetchone()
            if owner["lease"] != lease or owner["lease_until"] < time.time() or live["calendar"] != service or source_key(live) != key:
                raise google_services.ServiceError("sync_configuration_changed")
            seen = set()
            for event in events:
                external = event.get("external_id") or hashlib.sha256(json.dumps(event, sort_keys=True).encode()).hexdigest()
                seen.add(external)
                if event.get("deleted"):
                    changed += c.execute("DELETE FROM calendar_events_cache WHERE source_key=? AND external_id=?", (key, external)).rowcount
                    c.execute("DELETE FROM service_event_versions WHERE source_key=? AND external_id=?", (key, external))
                    continue
                fingerprint = hashlib.sha256(json.dumps(event, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                old = c.execute("SELECT fingerprint FROM service_event_versions WHERE source_key=? AND external_id=?", (key, external)).fetchone()
                if old and old[0] == fingerprint:
                    continue
                values = (event["title"], event["start_time"], event.get("end_time"), event.get("location"), event.get("description"), db.now_iso())
                updated = c.execute("UPDATE calendar_events_cache SET title=?,start_time=?,end_time=?,location=?,description=?,updated_at=? "
                                    "WHERE source_key=? AND external_id=?", (*values, key, external)).rowcount
                if not updated:
                    c.execute("INSERT INTO calendar_events_cache(title,start_time,end_time,location,description,updated_at,source,source_key,external_id) "
                              "VALUES(?,?,?,?,?,?,?,?,?)", (*values, service, key, external))
                c.execute("INSERT OR REPLACE INTO service_event_versions VALUES(?,?,?,?)", (key, external, fingerprint, event.get("remote_updated")))
                changed += 1
            if full:
                for old in list(c.execute("SELECT external_id FROM calendar_events_cache WHERE source_key=?", (key,))):
                    if old[0] not in seen:
                        changed += c.execute("DELETE FROM calendar_events_cache WHERE source_key=? AND external_id=?", (key, old[0])).rowcount
                        c.execute("DELETE FROM service_event_versions WHERE source_key=? AND external_id=?", (key, old[0]))
            c.execute("UPDATE service_sync_state SET slot=?,cursor=?,identity=?,last_success=?,error=NULL,"
                      "updated_count=?,lease=NULL,lease_until=0,next_attempt=0 WHERE service=? AND lease=?",
                      (slot, cursor, identity, db.now_iso(), changed, service, lease))
            resolve(service, c)
        return {"ok": True, "updated_count": changed}
    except Exception as exc:
        code = exc.code if isinstance(exc, google_services.ServiceError) else type(exc).__name__
        if code == "sync_configuration_changed":
            with db.get_connection() as c:
                c.execute("UPDATE service_sync_state SET lease=NULL,lease_until=0 WHERE service=? AND lease=?", (service, lease))
            return {"ok": False, "error": "同期中に設定が変更されたため中止しました。既存データを保持しています。"}
        error = LABELS.get(service, service) + ": " + code + "。認証・接続設定を確認してください。"
        with db.get_connection() as c:
            owned = c.execute("UPDATE service_sync_state SET last_failure=?,error=?,lease=NULL,lease_until=0,next_attempt=? WHERE service=? AND lease=?",
                              (db.now_iso(), error, time.time()+900, service, lease)).rowcount
        if owned:
            fail(service, error)
        return {"ok": False, "error": error}


def observe_notion():
    from . import config
    if not config.notion_configured():
        return
    with db.get_connection() as c:
        exists = c.execute("SELECT 1 FROM sqlite_master WHERE name='notion_task_sync_state'").fetchone()
        row = c.execute("SELECT * FROM notion_task_sync_state LIMIT 1").fetchone() if exists else None
    row = dict(row) if row else None
    if row and (row["last_error"] or row.get("daily_error")):
        fail("notion", "Notion同期に失敗しました。認証・DB共有・同期詳細を確認してください。")
    elif row and row["last_success_at"] and not row["last_failure_at"] and row.get("daily_status") not in {"running", "partial", "failed"}:
        resolve("notion")


def _loop():
    while not _stop.is_set():
        try:
            if settings.initialized():
                sync()
                observe_notion()
        except Exception:
            pass  # a service failure never stops Core or the next scheduled attempt
        _stop.wait(30)


def start():
    global _thread
    if _thread and _thread.is_alive():
        return
    ensure_schema()
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="petit-service-sync", daemon=True)
    _thread.start()


def stop():
    _stop.set()
    if _thread:
        _thread.join(timeout=2)
