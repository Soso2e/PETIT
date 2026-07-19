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
                "FROM conversations ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(r) for r in reversed(rows)]


def all_memory() -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, created_at, type, content, source, content_hash, embedding_model, embedding_version, indexed_at FROM memory ORDER BY id ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def normalized_hash(content: str) -> str:
    import hashlib
    normalized = " ".join(content.casefold().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def save_memory_item(content: str, mem_type: str, source: str) -> tuple[int, bool]:
    """Save a durable fact once. Exact normalized duplicates remain one record."""
    digest = normalized_hash(content)
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM memory WHERE content_hash = ?", (digest,)).fetchone()
        if row:
            return int(row["id"]), False
        cur = conn.execute(
            "INSERT INTO memory (created_at, type, content, source, content_hash) VALUES (?, ?, ?, ?, ?)",
            (now_iso(), mem_type, content.strip(), source, digest),
        )
        return int(cur.lastrowid), True


def update_memory_indexed(memory_id: int, model: str, version: str) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE memory SET embedding_model=?, embedding_version=?, indexed_at=? WHERE id=?", (model, version, now_iso(), memory_id))


def pending_episode_groups() -> list[list[dict[str, Any]]]:
    """Unfinalized turns grouped by browser session; never includes an episode twice."""
    with get_connection() as conn:
        rows = conn.execute("SELECT id, timestamp, user_text, assistant_text, used_tools, session_id FROM conversations WHERE episode_id IS NULL ORDER BY id ASC").fetchall()
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        item = dict(row)
        groups.setdefault(item.get("session_id") or "legacy", []).append(item)
    return list(groups.values())


def save_episode(data: dict[str, Any]) -> int:
    now = now_iso()
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO conversation_episodes (started_at, ended_at, title, summary, decisions, facts, work_in_progress, next_action, source_conversation_ids, content_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (data["started_at"], data["ended_at"], data["title"], data["summary"], data["decisions"], data["facts"], data["work_in_progress"], data["next_action"], data["source_ids"], data["content_hash"], now, now),
        )
        episode_id = int(cur.lastrowid)
        ids = json.loads(data["source_ids"])
        conn.executemany("UPDATE conversations SET episode_id=? WHERE id=? AND episode_id IS NULL", [(episode_id, item) for item in ids])
        return episode_id


def recent_episodes(limit: int = 20) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM conversation_episodes ORDER BY episode_id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(row) for row in reversed(rows)]


def all_episodes() -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM conversation_episodes ORDER BY episode_id ASC").fetchall()
    return [dict(row) for row in rows]


def update_episode_indexed(episode_id: int, model: str, version: str) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE conversation_episodes SET embedding_model=?, embedding_version=?, indexed_at=?, updated_at=? WHERE episode_id=?", (model, version, now_iso(), now_iso(), episode_id))


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

def create_job(
    job_type: str,
    input_json: str,
    *,
    session_id: str | None = None,
    request_id: str | None = None,
) -> int:
    if session_id is None or request_id is None:
        try:
            from . import request_context

            current_request, current_session = request_context.current_ids()
        except Exception:  # noqa: BLE001
            current_request, current_session = None, None
        request_id = request_id or current_request
        session_id = session_id or current_session
    ts = now_iso()
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO jobs (type, status, input_json, session_id, request_id, created_at, updated_at) "
            "VALUES (?, 'queued', ?, ?, ?, ?, ?)",
            (job_type, input_json, session_id, request_id, ts, ts),
        )
        return int(cur.lastrowid)


def claim_next_job() -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, type, input_json, session_id, request_id FROM jobs "
            "WHERE status = 'queued' ORDER BY id ASC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        claimed_at = now_iso()
        updated = conn.execute(
            "UPDATE jobs SET status = 'running', claimed_at = ?, updated_at = ? "
            "WHERE id = ? AND status = 'queued'",
            (claimed_at, claimed_at, row["id"]),
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


def undelivered_jobs(limit: int = 10, session_id: str | None = None) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 100))
    with get_connection() as conn:
        if session_id:
            rows = conn.execute(
                "SELECT id, type, status, result_text, error, session_id, request_id, created_at, updated_at "
                "FROM jobs WHERE delivered = 0 AND session_id = ? AND status IN ('done', 'failed') "
                "ORDER BY id ASC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, type, status, result_text, error, session_id, request_id, created_at, updated_at "
                "FROM jobs WHERE delivered = 0 AND status IN ('done', 'failed') "
                "ORDER BY id ASC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


def mark_jobs_delivered(job_ids: list[int], session_id: str | None = None) -> None:
    if not job_ids:
        return
    placeholders = ",".join("?" for _ in job_ids)
    delivered_at = now_iso()
    with get_connection() as conn:
        if session_id:
            conn.execute(
                f"UPDATE jobs SET delivered = 1, delivered_at = ?, updated_at = ? "
                f"WHERE session_id = ? AND id IN ({placeholders})",
                [delivered_at, delivered_at, session_id, *job_ids],
            )
        else:
            conn.execute(
                f"UPDATE jobs SET delivered = 1, delivered_at = ?, updated_at = ? WHERE id IN ({placeholders})",
                [delivered_at, delivered_at, *job_ids],
            )
