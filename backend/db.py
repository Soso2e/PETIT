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

CREATE TABLE IF NOT EXISTS tasks_cache (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL DEFAULT 'local',
    title       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'todo',
    due_date    TEXT,
    priority    TEXT,
    external_id TEXT,
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
"""


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
