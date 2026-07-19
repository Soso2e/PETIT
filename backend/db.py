"""SQLite access for PETIT.

The schema is a subset of the design in Concept.md, focused on what the MVP
actually uses. New tables can be added as features land.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config


class _ClosingConnection(sqlite3.Connection):
    """Commit/rollback like sqlite3's context manager, then close reliably."""

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        try:
            return bool(super().__exit__(exc_type, exc, traceback))
        finally:
            self.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT NOT NULL,
    user_text     TEXT NOT NULL,
    assistant_text TEXT NOT NULL,
    used_tools    TEXT,
    session_id    TEXT,
    episode_id    INTEGER
);

CREATE TABLE IF NOT EXISTS memory (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    type       TEXT NOT NULL DEFAULT 'note',
    content    TEXT NOT NULL,
    source     TEXT NOT NULL DEFAULT 'explicit',
    content_hash TEXT,
    embedding_model TEXT,
    embedding_version TEXT,
    indexed_at TEXT
);

CREATE TABLE IF NOT EXISTS conversation_episodes (
    episode_id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    decisions TEXT NOT NULL DEFAULT '[]',
    facts TEXT NOT NULL DEFAULT '[]',
    work_in_progress TEXT NOT NULL DEFAULT '[]',
    next_action TEXT NOT NULL DEFAULT '[]',
    source_conversation_ids TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    embedding_model TEXT,
    embedding_version TEXT,
    indexed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS summaries (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at   TEXT NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'interval',
    period_start TEXT,
    period_end   TEXT,
    last_conv_id INTEGER NOT NULL DEFAULT 0,
    conv_count   INTEGER NOT NULL DEFAULT 0,
    summary      TEXT NOT NULL,
    facts        TEXT
);

CREATE TABLE IF NOT EXISTS tasks_cache (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL DEFAULT 'local',
    title       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'todo',
    due_date    TEXT,
    priority    TEXT,
    category    TEXT,
    area        TEXT,
    reason      TEXT,
    external_id TEXT,
    url         TEXT,
    done_date   TEXT,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS calendar_events_cache (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL DEFAULT 'local',
    title       TEXT NOT NULL,
    start_time  TEXT,
    end_time    TEXT,
    location    TEXT,
    description TEXT,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_state (
    source              TEXT PRIMARY KEY,
    last_success_at     TEXT,
    last_failure_at     TEXT,
    last_error          TEXT,
    synced_count        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS handoff_notes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT NOT NULL,
    current_project TEXT,
    stopped_at      TEXT,
    next_action     TEXT NOT NULL,
    blockers        TEXT,
    note            TEXT,
    source          TEXT NOT NULL DEFAULT 'manual'
);

CREATE TABLE IF NOT EXISTS jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    type        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'queued',
    input_json  TEXT NOT NULL DEFAULT '{}',
    result_text TEXT,
    error       TEXT,
    delivered   INTEGER NOT NULL DEFAULT 0,
    session_id  TEXT,
    request_id  TEXT,
    claimed_at  TEXT,
    delivered_at TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=5.0, factory=_ClosingConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db() -> None:
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection()
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.executescript(SCHEMA)
        _ensure_columns(
            conn,
            "tasks_cache",
            {
                "category": "TEXT",
                "area": "TEXT",
                "reason": "TEXT",
                "url": "TEXT",
                "done_date": "TEXT",
            },
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_cache_area ON tasks_cache(area, status)")
        _ensure_columns(conn, "conversations", {"session_id": "TEXT", "episode_id": "INTEGER"})
        conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_episode ON conversations(episode_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_session ON conversations(session_id, id)")
        _ensure_columns(conn, "memory", {"source": "TEXT NOT NULL DEFAULT 'explicit'", "content_hash": "TEXT", "embedding_model": "TEXT", "embedding_version": "TEXT", "indexed_at": "TEXT"})
        _ensure_columns(conn, "calendar_events_cache", {"source_key": "TEXT", "external_id": "TEXT"})
        _ensure_columns(
            conn,
            "jobs",
            {
                "session_id": "TEXT",
                "request_id": "TEXT",
                "claimed_at": "TEXT",
                "delivered_at": "TEXT",
            },
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_calendar_source_external "
            "ON calendar_events_cache(source_key, external_id) "
            "WHERE source_key IS NOT NULL AND external_id IS NOT NULL"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_delivery ON jobs(session_id, delivered, status, id)")
        conn.commit()
    finally:
        conn.close()


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, col_type in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {col_type}")


def sync_state(source: str) -> dict[str, Any]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM sync_state WHERE source = ?", (source,)).fetchone()
    return dict(row) if row else {"source": source, "last_success_at": None, "last_failure_at": None, "last_error": None, "synced_count": 0}


def all_sync_states() -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM sync_state ORDER BY source").fetchall()
    return [dict(row) for row in rows]


def record_sync_success(source: str, synced_count: int) -> str:
    now = now_iso()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO sync_state(source, last_success_at, last_failure_at, last_error, synced_count) VALUES (?, ?, NULL, NULL, ?) "
            "ON CONFLICT(source) DO UPDATE SET last_success_at=excluded.last_success_at, last_failure_at=NULL, last_error=NULL, synced_count=excluded.synced_count",
            (source, now, synced_count),
        )
    return now


def record_sync_failure(source: str, error: str) -> str:
    now = now_iso()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO sync_state(source, last_failure_at, last_error, synced_count) VALUES (?, ?, ?, 0) "
            "ON CONFLICT(source) DO UPDATE SET last_failure_at=excluded.last_failure_at, last_error=excluded.last_error",
            (source, now, error),
        )
    return now


def save_conversation(user_text: str, assistant_text: str, used_tools: str | None = None, session_id: str | None = None) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO conversations (timestamp, user_text, assistant_text, used_tools, session_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (now_iso(), user_text, assistant_text, used_tools, session_id),
        )
        return int(cur.lastrowid)


def recent_conversations(limit: int = 20, session_id: str | None = None) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 200))
    with get_connection() as conn:
        if session_id:
            rows = conn.execute(
                "SELECT id, timestamp, user_text, assistant_text, used_tools, session_id "
                "FROM conversations WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, timestamp, user_text, assistant_text, used_tools, session_id "
                "FROM conversations ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
    return [dict(row) for row in reversed(rows)]
