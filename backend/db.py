"""SQLite access for PETIT.

The schema is a subset of the design in Concept.md, focused on what the MVP
actually uses. New tables can be added as features land.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT NOT NULL,
    user_text     TEXT NOT NULL,
    assistant_text TEXT NOT NULL,
    used_tools    TEXT
);

CREATE TABLE IF NOT EXISTS memory (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    type       TEXT NOT NULL DEFAULT 'note',
    content    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS summaries (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at   TEXT NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'interval',  -- interval | daily
    period_start TEXT,
    period_end   TEXT,
    last_conv_id INTEGER NOT NULL DEFAULT 0,
    conv_count   INTEGER NOT NULL DEFAULT 0,
    summary      TEXT NOT NULL,
    facts        TEXT  -- JSON-encoded list of extracted durable facts/tasks
);

CREATE TABLE IF NOT EXISTS tasks_cache (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL DEFAULT 'local',
    title       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'todo',
    due_date    TEXT,
    priority    TEXT,
    category    TEXT,
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
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        _ensure_columns(
            conn,
            "tasks_cache",
            {
                "category": "TEXT",
                "reason": "TEXT",
                "url": "TEXT",
                "done_date": "TEXT",
            },
        )


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, col_type in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {col_type}")


def save_conversation(user_text: str, assistant_text: str, used_tools: str | None = None) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO conversations (timestamp, user_text, assistant_text, used_tools) "
            "VALUES (?, ?, ?, ?)",
            (now_iso(), user_text, assistant_text, used_tools),
        )
        return int(cur.lastrowid)


def recent_conversations(limit: int = 20) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, timestamp, user_text, assistant_text, used_tools "
            "FROM conversations ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def all_memory() -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, created_at, type, content FROM memory ORDER BY id ASC"
        ).fetchall()
    return [dict(r) for r in rows]


# --- Summaries ---------------------------------------------------------------

def last_summarized_conv_id() -> int:
    """Highest conversation id that has already been folded into a summary."""
    with get_connection() as conn:
        row = conn.execute("SELECT MAX(last_conv_id) AS m FROM summaries").fetchone()
    return int(row["m"]) if row and row["m"] is not None else 0


def conversations_after(conv_id: int, limit: int = 500) -> list[dict[str, Any]]:
    """Conversation turns newer than conv_id, oldest first (chronological)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, timestamp, user_text, assistant_text, used_tools "
            "FROM conversations WHERE id > ? ORDER BY id ASC LIMIT ?",
            (conv_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def save_summary(
    summary: str,
    facts: str | None,
    kind: str,
    period_start: str | None,
    period_end: str | None,
    last_conv_id: int,
    conv_count: int,
) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO summaries "
            "(created_at, kind, period_start, period_end, last_conv_id, conv_count, summary, facts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (now_iso(), kind, period_start, period_end, last_conv_id, conv_count, summary, facts),
        )
        return int(cur.lastrowid)


def recent_summaries(limit: int = 20) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, created_at, kind, period_start, period_end, conv_count, summary, facts "
            "FROM summaries ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


# --- Handoff notes -----------------------------------------------------------

def save_handoff_note(
    current_project: str | None,
    stopped_at: str | None,
    next_action: str,
    blockers: str | None,
    note: str | None,
    source: str = "manual",
) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO handoff_notes "
            "(created_at, current_project, stopped_at, next_action, blockers, note, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (now_iso(), current_project, stopped_at, next_action, blockers, note, source),
        )
        return int(cur.lastrowid)


def recent_handoff_notes(limit: int = 5) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, created_at, current_project, stopped_at, next_action, blockers, note, source "
            "FROM handoff_notes ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


# --- Background jobs ---------------------------------------------------------

def create_job(job_type: str, input_json: str) -> int:
    ts = now_iso()
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO jobs (type, status, input_json, created_at, updated_at) "
            "VALUES (?, 'queued', ?, ?, ?)",
            (job_type, input_json, ts, ts),
        )
        return int(cur.lastrowid)


def claim_next_job() -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, type, input_json FROM jobs "
            "WHERE status = 'queued' ORDER BY id ASC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        updated = conn.execute(
            "UPDATE jobs SET status = 'running', updated_at = ? "
            "WHERE id = ? AND status = 'queued'",
            (now_iso(), row["id"]),
        ).rowcount
        if not updated:
            return None
        return dict(row)


def finish_job(job_id: int, result_text: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE jobs SET status = 'done', result_text = ?, error = NULL, updated_at = ? "
            "WHERE id = ?",
            (result_text, now_iso(), job_id),
        )


def fail_job(job_id: int, error: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE jobs SET status = 'failed', error = ?, updated_at = ? WHERE id = ?",
            (error, now_iso(), job_id),
        )


def undelivered_jobs(limit: int = 10) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, type, status, result_text, error, created_at, updated_at "
            "FROM jobs WHERE delivered = 0 AND status IN ('done', 'failed') "
            "ORDER BY id ASC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def mark_jobs_delivered(job_ids: list[int]) -> None:
    if not job_ids:
        return
    placeholders = ",".join("?" for _ in job_ids)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE jobs SET delivered = 1, updated_at = ? WHERE id IN ({placeholders})",
            [now_iso(), *job_ids],
        )

