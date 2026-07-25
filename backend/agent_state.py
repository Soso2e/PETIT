"""Short-lived resumable state for confirmation-gated Agent writes."""
from __future__ import annotations

import json
import time
from typing import Any
from uuid import uuid4

from . import db

_TTL_SECONDS = 1800


def ensure_schema() -> None:
    with db.get_connection() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS agent_run_states ("
            "resume_id TEXT PRIMARY KEY, state_json TEXT NOT NULL, created_at REAL NOT NULL)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_run_states_created "
            "ON agent_run_states(created_at)"
        )


def save(state: dict[str, Any]) -> str:
    ensure_schema()
    resume_id = uuid4().hex
    now = time.time()
    with db.get_connection() as conn:
        conn.execute("DELETE FROM agent_run_states WHERE created_at < ?", (now - _TTL_SECONDS,))
        conn.execute(
            "INSERT INTO agent_run_states(resume_id, state_json, created_at) VALUES (?, ?, ?)",
            (resume_id, json.dumps(state, ensure_ascii=False, default=str), now),
        )
    return resume_id


def load(resume_id: str) -> dict[str, Any] | None:
    ensure_schema()
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT state_json, created_at FROM agent_run_states WHERE resume_id=?",
            (str(resume_id or ""),),
        ).fetchone()
    if row is None:
        return None
    if time.time() - float(row["created_at"]) > _TTL_SECONDS:
        delete(resume_id)
        return None
    try:
        value = json.loads(row["state_json"])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def delete(resume_id: str) -> None:
    ensure_schema()
    with db.get_connection() as conn:
        conn.execute("DELETE FROM agent_run_states WHERE resume_id=?", (str(resume_id or ""),))
