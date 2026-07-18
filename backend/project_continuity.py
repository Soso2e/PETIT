"""Project continuity storage for PETIT.

This module owns the local mapping layer that connects PETIT conversations and
future external sources to one stable internal project id.  External services
remain canonical for their own data; these tables only keep identity, links,
and restart checkpoints.
"""
from __future__ import annotations

import json
import re
import unicodedata
import uuid
from typing import Any

from . import db

PROJECT_RELATIONS = {"primary", "referenced", "comparison", "dependency"}
PROJECT_STAGES = {
    "started",
    "implemented",
    "automated_tests_verified",
    "ui_verified",
    "deployed",
    "production_verified",
    "paused",
    "interrupted",
    "blocked",
    "completed",
}

PROJECT_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    description TEXT,
    canonical_provider TEXT,
    canonical_external_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_aliases (
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, normalized_alias)
);
CREATE INDEX IF NOT EXISTS idx_project_aliases_normalized
ON project_aliases(normalized_alias);

CREATE TABLE IF NOT EXISTS project_source_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    external_id TEXT NOT NULL,
    external_url TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'active',
    confirmed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(provider, external_id)
);
CREATE INDEX IF NOT EXISTS idx_project_source_links_project
ON project_source_links(project_id, status);

CREATE TABLE IF NOT EXISTS episode_project_links (
    episode_id INTEGER NOT NULL REFERENCES conversation_episodes(episode_id) ON DELETE CASCADE,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    relation TEXT NOT NULL DEFAULT 'primary',
    confidence REAL,
    confirmed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    PRIMARY KEY (episode_id, project_id)
);
CREATE INDEX IF NOT EXISTS idx_episode_project_links_project
ON episode_project_links(project_id, episode_id);

CREATE TABLE IF NOT EXISTS active_project_state (
    user_id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    started_at TEXT,
    last_interaction_at TEXT,
    source_conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_checkpoints (
    user_id TEXT NOT NULL,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    stage TEXT NOT NULL DEFAULT 'started',
    last_summary TEXT,
    next_action TEXT,
    blockers TEXT NOT NULL DEFAULT '[]',
    completed_evidence TEXT NOT NULL DEFAULT '[]',
    unverified_items TEXT NOT NULL DEFAULT '[]',
    last_session_started_at TEXT,
    last_session_ended_at TEXT,
    source_conversation_ids TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, project_id)
);
"""


def ensure_project_schema() -> None:
    """Create continuity tables without altering existing PETIT tables."""
    with db.get_connection() as conn:
        conn.executescript(PROJECT_SCHEMA)


def normalize_alias(value: str) -> str:
    """Normalize human project aliases while preserving Japanese text."""
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return re.sub(r"[\W_]+", "", normalized, flags=re.UNICODE)


def _require_text(value: str, field: str) -> str:
    result = value.strip()
    if not result:
        raise ValueError(f"{field} is required")
    return result


def _json_list(value: list[Any] | None, fallback: str = "[]") -> str:
    if value is None:
        return fallback
    return json.dumps(value, ensure_ascii=False)


def _decode_json_list(value: str | None) -> list[Any]:
    try:
        data = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def create_project(
    name: str,
    *,
    description: str | None = None,
    canonical_provider: str | None = None,
    canonical_external_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    ensure_project_schema()
    name = _require_text(name, "name")
    project_id = project_id or str(uuid.uuid4())
    now = db.now_iso()
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, status, description, canonical_provider, canonical_external_id, created_at, updated_at) "
            "VALUES (?, ?, 'active', ?, ?, ?, ?, ?)",
            (
                project_id,
                name,
                description.strip() if description else None,
                canonical_provider.strip() if canonical_provider else None,
                canonical_external_id.strip() if canonical_external_id else None,
                now,
                now,
            ),
        )
        _insert_alias(conn, project_id, name, now)
    return get_project(project_id) or {}


def get_project(project_id: str) -> dict[str, Any] | None:
    ensure_project_schema()
    with db.get_connection() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return dict(row) if row else None


def add_project_alias(project_id: str, alias: str) -> bool:
    ensure_project_schema()
    alias = _require_text(alias, "alias")
    now = db.now_iso()
    with db.get_connection() as conn:
        return _insert_alias(conn, project_id, alias, now)


def _insert_alias(conn: Any, project_id: str, alias: str, now: str) -> bool:
    normalized = normalize_alias(alias)
    if not normalized:
        raise ValueError("alias must contain searchable characters")
    project = conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not project:
        raise ValueError("project not found")
    cursor = conn.execute(
        "INSERT OR IGNORE INTO project_aliases (project_id, alias, normalized_alias, created_at) VALUES (?, ?, ?, ?)",
        (project_id, alias.strip(), normalized, now),
    )
    return cursor.rowcount > 0


def find_projects_by_alias(alias: str) -> list[dict[str, Any]]:
    ensure_project_schema()
    normalized = normalize_alias(alias)
    if not normalized:
        return []
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT p.*, a.alias AS matched_alias FROM project_aliases a "
            "JOIN projects p ON p.id = a.project_id "
            "WHERE a.normalized_alias = ? AND p.status != 'archived' "
            "ORDER BY p.updated_at DESC, p.name ASC",
            (normalized,),
        ).fetchall()
    return [dict(row) for row in rows]


def link_project_source(
    project_id: str,
    provider: str,
    external_id: str,
    *,
    external_url: str | None = None,
    metadata: dict[str, Any] | None = None,
    confirmed: bool = False,
) -> dict[str, Any]:
    ensure_project_schema()
    provider = _require_text(provider, "provider").casefold()
    external_id = _require_text(external_id, "external_id")
    now = db.now_iso()
    metadata_json = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)
    with db.get_connection() as conn:
        if not conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone():
            raise ValueError("project not found")
        existing = conn.execute(
            "SELECT * FROM project_source_links WHERE provider = ? AND external_id = ?",
            (provider, external_id),
        ).fetchone()
        if existing and existing["project_id"] != project_id:
            raise ValueError("source is already linked to another project")
        confirmed_at = now if confirmed else (existing["confirmed_at"] if existing else None)
        if existing:
            conn.execute(
                "UPDATE project_source_links SET external_url=?, metadata_json=?, status='active', confirmed_at=?, updated_at=? WHERE id=?",
                (external_url, metadata_json, confirmed_at, now, existing["id"]),
            )
            link_id = int(existing["id"])
        else:
            cursor = conn.execute(
                "INSERT INTO project_source_links (project_id, provider, external_id, external_url, metadata_json, status, confirmed_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)",
                (project_id, provider, external_id, external_url, metadata_json, confirmed_at, now, now),
            )
            link_id = int(cursor.lastrowid)
    return get_project_source_link(link_id) or {}


def get_project_source_link(link_id: int) -> dict[str, Any] | None:
    ensure_project_schema()
    with db.get_connection() as conn:
        row = conn.execute("SELECT * FROM project_source_links WHERE id = ?", (link_id,)).fetchone()
    if not row:
        return None
    result = dict(row)
    try:
        result["metadata"] = json.loads(result.pop("metadata_json"))
    except json.JSONDecodeError:
        result["metadata"] = {}
    return result


def confirm_project_source_link(link_id: int) -> dict[str, Any]:
    ensure_project_schema()
    now = db.now_iso()
    with db.get_connection() as conn:
        cursor = conn.execute(
            "UPDATE project_source_links SET confirmed_at=?, status='active', updated_at=? WHERE id=?",
            (now, now, link_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("source link not found")
    return get_project_source_link(link_id) or {}


def remove_project_source_link(link_id: int) -> dict[str, Any]:
    ensure_project_schema()
    now = db.now_iso()
    with db.get_connection() as conn:
        cursor = conn.execute(
            "UPDATE project_source_links SET status='removed', updated_at=? WHERE id=?",
            (now, link_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("source link not found")
    return get_project_source_link(link_id) or {}


def link_episode_to_project(
    episode_id: int,
    project_id: str,
    *,
    relation: str = "primary",
    confidence: float | None = None,
    confirmed: bool = False,
) -> dict[str, Any]:
    ensure_project_schema()
    if relation not in PROJECT_RELATIONS:
        raise ValueError(f"invalid relation: {relation}")
    if confidence is not None and not 0 <= confidence <= 1:
        raise ValueError("confidence must be between 0 and 1")
    now = db.now_iso()
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO episode_project_links (episode_id, project_id, relation, confidence, confirmed, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(episode_id, project_id) DO UPDATE SET relation=excluded.relation, confidence=excluded.confidence, confirmed=excluded.confirmed",
            (episode_id, project_id, relation, confidence, int(confirmed), now),
        )
        row = conn.execute(
            "SELECT * FROM episode_project_links WHERE episode_id=? AND project_id=?",
            (episode_id, project_id),
        ).fetchone()
    return dict(row)


def set_active_project(
    user_id: str,
    project_id: str | None,
    *,
    source_conversation_id: int | None = None,
) -> dict[str, Any] | None:
    ensure_project_schema()
    user_id = _require_text(user_id, "user_id")
    now = db.now_iso()
    with db.get_connection() as conn:
        if project_id and not conn.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
            raise ValueError("project not found")
        existing = conn.execute("SELECT project_id, started_at FROM active_project_state WHERE user_id=?", (user_id,)).fetchone()
        started_at = existing["started_at"] if existing and existing["project_id"] == project_id else (now if project_id else None)
        conn.execute(
            "INSERT INTO active_project_state (user_id, project_id, started_at, last_interaction_at, source_conversation_id, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET project_id=excluded.project_id, started_at=excluded.started_at, "
            "last_interaction_at=excluded.last_interaction_at, source_conversation_id=excluded.source_conversation_id, updated_at=excluded.updated_at",
            (user_id, project_id, started_at, now, source_conversation_id, now),
        )
    return get_active_project(user_id)


def get_active_project(user_id: str) -> dict[str, Any] | None:
    ensure_project_schema()
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT s.user_id, s.project_id, s.started_at, s.last_interaction_at, s.source_conversation_id, s.updated_at, "
            "p.name, p.status, p.description "
            "FROM active_project_state s LEFT JOIN projects p ON p.id=s.project_id WHERE s.user_id=?",
            (user_id,),
        ).fetchone()
    return dict(row) if row and row["project_id"] else None


def save_project_checkpoint(
    user_id: str,
    project_id: str,
    *,
    stage: str | None = None,
    last_summary: str | None = None,
    next_action: str | None = None,
    blockers: list[str] | None = None,
    completed_evidence: list[str] | None = None,
    unverified_items: list[str] | None = None,
    last_session_started_at: str | None = None,
    last_session_ended_at: str | None = None,
    source_conversation_ids: list[int] | None = None,
) -> dict[str, Any]:
    ensure_project_schema()
    user_id = _require_text(user_id, "user_id")
    if stage is not None and stage not in PROJECT_STAGES:
        raise ValueError(f"invalid stage: {stage}")
    now = db.now_iso()
    with db.get_connection() as conn:
        if not conn.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
            raise ValueError("project not found")
        old = conn.execute(
            "SELECT * FROM project_checkpoints WHERE user_id=? AND project_id=?",
            (user_id, project_id),
        ).fetchone()
        old_data = dict(old) if old else {}
        values = {
            "stage": stage if stage is not None else old_data.get("stage", "started"),
            "last_summary": last_summary if last_summary is not None else old_data.get("last_summary"),
            "next_action": next_action if next_action is not None else old_data.get("next_action"),
            "blockers": _json_list(blockers, old_data.get("blockers", "[]")),
            "completed_evidence": _json_list(completed_evidence, old_data.get("completed_evidence", "[]")),
            "unverified_items": _json_list(unverified_items, old_data.get("unverified_items", "[]")),
            "last_session_started_at": last_session_started_at if last_session_started_at is not None else old_data.get("last_session_started_at"),
            "last_session_ended_at": last_session_ended_at if last_session_ended_at is not None else old_data.get("last_session_ended_at"),
            "source_conversation_ids": _json_list(source_conversation_ids, old_data.get("source_conversation_ids", "[]")),
            "created_at": old_data.get("created_at", now),
        }
        conn.execute(
            "INSERT INTO project_checkpoints (user_id, project_id, stage, last_summary, next_action, blockers, completed_evidence, unverified_items, "
            "last_session_started_at, last_session_ended_at, source_conversation_ids, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id, project_id) DO UPDATE SET stage=excluded.stage, last_summary=excluded.last_summary, "
            "next_action=excluded.next_action, blockers=excluded.blockers, completed_evidence=excluded.completed_evidence, "
            "unverified_items=excluded.unverified_items, last_session_started_at=excluded.last_session_started_at, "
            "last_session_ended_at=excluded.last_session_ended_at, source_conversation_ids=excluded.source_conversation_ids, updated_at=excluded.updated_at",
            (
                user_id,
                project_id,
                values["stage"],
                values["last_summary"],
                values["next_action"],
                values["blockers"],
                values["completed_evidence"],
                values["unverified_items"],
                values["last_session_started_at"],
                values["last_session_ended_at"],
                values["source_conversation_ids"],
                values["created_at"],
                now,
            ),
        )
    return get_project_checkpoint(user_id, project_id) or {}


def get_project_checkpoint(user_id: str, project_id: str) -> dict[str, Any] | None:
    ensure_project_schema()
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT c.*, p.name AS project_name FROM project_checkpoints c "
            "JOIN projects p ON p.id=c.project_id WHERE c.user_id=? AND c.project_id=?",
            (user_id, project_id),
        ).fetchone()
    if not row:
        return None
    result = dict(row)
    for field in ("blockers", "completed_evidence", "unverified_items", "source_conversation_ids"):
        result[field] = _decode_json_list(result[field])
    return result
