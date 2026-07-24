"""SQLite schema, webhook verification, and inbox persistence."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from .. import config, db, task_sync_queue

log = logging.getLogger(__name__)

SYNC_SOURCE = "notion:tasks:live"
PAGE_EVENTS = {
    "page.created",
    "page.properties_updated",
    "page.content_updated",
    "page.moved",
    "page.deleted",
    "page.undeleted",
}
FULL_SYNC_EVENTS = {
    "database.content_updated",
    "database.schema_updated",
    "data_source.content_updated",
    "data_source.schema_updated",
}
MAX_INBOX_ATTEMPTS = 8

_SCHEMA = """
CREATE TABLE IF NOT EXISTS notion_task_sync_state (
    provider TEXT PRIMARY KEY,
    last_started_at TEXT,
    last_success_at TEXT,
    last_failure_at TEXT,
    last_error TEXT,
    last_full_sync_at TEXT,
    last_webhook_at TEXT,
    last_event_id TEXT,
    pull_cursor_at TEXT,
    full_sync_requested INTEGER NOT NULL DEFAULT 0,
    webhook_verification_token TEXT,
    synced_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS notion_task_inbox (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    entity_id TEXT,
    entity_type TEXT,
    event_timestamp TEXT,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    processed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_notion_task_inbox_ready
ON notion_task_inbox(status, next_attempt_at, event_timestamp, event_id);

CREATE TABLE IF NOT EXISTS notion_task_remote_snapshots (
    external_id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    source_updated_at TEXT,
    archived INTEGER NOT NULL DEFAULT 0,
    received_at TEXT NOT NULL
);
"""


def json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def json_loads(value: str | None, default: Any = None) -> Any:
    try:
        return json.loads(value or "")
    except (json.JSONDecodeError, TypeError):
        return {} if default is None else default


def normalize_id(value: Any) -> str:
    return str(value or "").replace("-", "").strip().casefold()


def parse_time(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def due(last_at: str | None, interval_seconds: float) -> bool:
    last = parse_time(last_at)
    if last is None:
        return True
    return datetime.now(timezone.utc) >= last + timedelta(seconds=max(1.0, float(interval_seconds)))


def ensure_schema() -> None:
    task_sync_queue.ensure_task_sync_schema()
    with db.get_connection() as conn:
        existing = {str(row["name"]) for row in conn.execute("PRAGMA table_info(tasks_cache)").fetchall()}
        if "remote_deleted_at" not in existing:
            conn.execute('ALTER TABLE tasks_cache ADD COLUMN "remote_deleted_at" TEXT')
        conn.executescript(_SCHEMA)
        conn.execute(
            "INSERT OR IGNORE INTO notion_task_sync_state(provider, synced_count) VALUES (?, 0)",
            (SYNC_SOURCE,),
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_cache_remote_deleted "
            "ON tasks_cache(remote_deleted_at, source, sync_status)"
        )


def state_row(conn: Any) -> Any:
    return conn.execute(
        "SELECT * FROM notion_task_sync_state WHERE provider=?",
        (SYNC_SOURCE,),
    ).fetchone()


def state() -> dict[str, Any]:
    ensure_schema()
    with db.get_connection() as conn:
        return dict(state_row(conn) or {})


def task_source_ids() -> set[str]:
    return {
        normalized
        for value in (config.NOTION_TASKS_DB_ID, config.NOTION_TASKS_DATA_SOURCE_ID)
        if (normalized := normalize_id(value))
    }


def stored_verification_token() -> str:
    configured = str(config.NOTION_WEBHOOK_VERIFICATION_TOKEN or "").strip()
    if configured:
        return configured
    current = state()
    return str(current.get("webhook_verification_token") or "")


def accept_verification_token(token: str) -> dict[str, Any]:
    """Persist the one-time token sent by Notion during subscription setup."""
    token = str(token or "").strip()
    if not token:
        return {"accepted": False, "error": "verification_token が空です。"}
    ensure_schema()
    with db.get_connection() as conn:
        row = state_row(conn)
        current = str(row["webhook_verification_token"] or "") if row else ""
        configured = str(config.NOTION_WEBHOOK_VERIFICATION_TOKEN or "").strip()
        if configured:
            return {"accepted": True, "stored": False, "source": "environment"}
        if current and current != token and not config.NOTION_WEBHOOK_ALLOW_TOKEN_ROTATION:
            return {
                "accepted": False,
                "error": "既存Webhook tokenと異なるため更新を拒否しました。再作成時はrotation設定を有効にしてください。",
            }
        conn.execute(
            "UPDATE notion_task_sync_state SET webhook_verification_token=? WHERE provider=?",
            (token, SYNC_SOURCE),
        )
    log.warning("Notion webhook verification token received and stored locally: %s", token)
    return {"accepted": True, "stored": True, "source": "sqlite"}


def verify_webhook_signature(raw_body: bytes, signature: str | None) -> bool:
    if not config.NOTION_WEBHOOK_REQUIRE_SIGNATURE:
        return True
    token = stored_verification_token()
    supplied = str(signature or "").strip()
    if not token or not supplied:
        return False
    expected = "sha256=" + hmac.new(token.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, supplied)


def enqueue_webhook_event(payload: dict[str, Any]) -> dict[str, Any]:
    ensure_schema()
    event_id = str(payload.get("id") or "").strip()
    event_type = str(payload.get("type") or "").strip()
    entity = payload.get("entity") if isinstance(payload.get("entity"), dict) else {}
    entity_id = str(entity.get("id") or "").strip() or None
    entity_type = str(entity.get("type") or "").strip() or None
    if not event_id or not event_type:
        return {"accepted": False, "error": "Webhook event id/type がありません。"}
    if event_type not in PAGE_EVENTS | FULL_SYNC_EVENTS:
        return {"accepted": True, "ignored": True, "event_id": event_id, "event_type": event_type}
    now = db.now_iso()
    with db.get_connection() as conn:
        inserted = conn.execute(
            "INSERT OR IGNORE INTO notion_task_inbox "
            "(event_id, event_type, entity_id, entity_type, event_timestamp, payload_json, status, attempts, next_attempt_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)",
            (
                event_id,
                event_type,
                entity_id,
                entity_type,
                payload.get("timestamp"),
                json_dumps(payload),
                now,
                now,
                now,
            ),
        ).rowcount
        conn.execute(
            "UPDATE notion_task_sync_state SET last_webhook_at=?, last_event_id=? WHERE provider=?",
            (now, event_id, SYNC_SOURCE),
        )
    return {
        "accepted": True,
        "duplicate": not bool(inserted),
        "event_id": event_id,
        "event_type": event_type,
    }


def claim_inbox() -> dict[str, Any] | None:
    ensure_schema()
    now = db.now_iso()
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM notion_task_inbox WHERE status IN ('pending','failed') AND attempts < ? "
            "AND (next_attempt_at IS NULL OR next_attempt_at <= ?) "
            "ORDER BY event_timestamp, event_id LIMIT 1",
            (MAX_INBOX_ATTEMPTS, now),
        ).fetchone()
        if row is None:
            return None
        attempts = int(row["attempts"] or 0) + 1
        updated = conn.execute(
            "UPDATE notion_task_inbox SET status='processing', attempts=?, updated_at=? "
            "WHERE event_id=? AND status IN ('pending','failed')",
            (attempts, now, row["event_id"]),
        ).rowcount
        if not updated:
            return None
        item = dict(row)
        item["attempts"] = attempts
        return item


def _retry_at(attempts: int) -> str:
    seconds = min(3600, 15 * (2 ** max(0, attempts - 1)))
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="seconds")


def finish_inbox(event_id: str, status: str, *, error: str | None = None) -> None:
    now = db.now_iso()
    with db.get_connection() as conn:
        if status == "done":
            conn.execute(
                "UPDATE notion_task_inbox SET status='done', last_error=NULL, next_attempt_at=NULL, "
                "processed_at=?, updated_at=? WHERE event_id=?",
                (now, now, event_id),
            )
            return
        row = conn.execute(
            "SELECT attempts FROM notion_task_inbox WHERE event_id=?",
            (event_id,),
        ).fetchone()
        attempts = int(row["attempts"] or 1) if row else 1
        conn.execute(
            "UPDATE notion_task_inbox SET status='failed', last_error=?, next_attempt_at=?, updated_at=? "
            "WHERE event_id=?",
            (str(error or "unknown")[:500], _retry_at(attempts), now, event_id),
        )
