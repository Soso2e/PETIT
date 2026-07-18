"""Relation-aware Notion project/task synchronization for PETIT Phase 2.

Notion remains canonical for personal projects and tasks. PETIT caches source
facts and stores mapping candidates, but never confirms a Notion project link from
name similarity alone.
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable

from . import config, db, project_continuity
from .notion_client import NotionError, query_projects_database, query_tasks_database_v2

PROJECT_SOURCE = "notion:projects"
TASK_SOURCE = "notion:tasks"
_PROVIDER = "notion"
_last_sync_monotonic: dict[str, float] = {}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS notion_projects_cache (
    external_id TEXT PRIMARY KEY,
    internal_project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'unknown',
    owner_external_ids TEXT NOT NULL DEFAULT '[]',
    priority TEXT,
    period_start TEXT,
    period_end TEXT,
    summary TEXT,
    task_external_ids TEXT NOT NULL DEFAULT '[]',
    blocked_by_external_ids TEXT NOT NULL DEFAULT '[]',
    url TEXT,
    source_created_at TEXT,
    source_updated_at TEXT,
    synced_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notion_projects_internal
ON notion_projects_cache(internal_project_id, status);

CREATE TABLE IF NOT EXISTS notion_source_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    external_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    title TEXT NOT NULL,
    external_url TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    suggested_project_ids TEXT NOT NULL DEFAULT '[]',
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(provider, external_id)
);
CREATE INDEX IF NOT EXISTS idx_notion_candidates_status
ON notion_source_candidates(status, source_type, updated_at);
"""

_TASK_COLUMNS = {
    "project_external_id": "TEXT",
    "project_external_ids": "TEXT NOT NULL DEFAULT '[]'",
    "project_id": "TEXT",
    "assignee_external_ids": "TEXT NOT NULL DEFAULT '[]'",
    "parent_external_id": "TEXT",
    "parent_external_ids": "TEXT NOT NULL DEFAULT '[]'",
    "subtask_external_ids": "TEXT NOT NULL DEFAULT '[]'",
    "summary": "TEXT",
    "source_updated_at": "TEXT",
}


def _ensure_columns(conn: Any, table: str, columns: dict[str, str]) -> None:
    existing = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}')


def ensure_notion_project_schema() -> None:
    project_continuity.ensure_project_schema()
    with db.get_connection() as conn:
        conn.executescript(_SCHEMA)
        _ensure_columns(conn, "tasks_cache", _TASK_COLUMNS)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_cache_project_id ON tasks_cache(project_id, status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_cache_project_external ON tasks_cache(project_external_id)"
        )


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else [], ensure_ascii=False, sort_keys=True)


def _confirmed_internal_project(conn: Any, external_id: str) -> str | None:
    row = conn.execute(
        "SELECT project_id FROM project_source_links WHERE provider=? AND external_id=? "
        "AND status='active' AND confirmed_at IS NOT NULL",
        (_PROVIDER, external_id),
    ).fetchone()
    return str(row["project_id"]) if row else None


def _suggested_projects(title: str) -> list[str]:
    return [str(item["id"]) for item in project_continuity.find_projects_by_alias(title)]


def _upsert_candidate(
    conn: Any,
    project: dict[str, Any],
    *,
    internal_project_id: str | None,
    now: str,
) -> None:
    suggestions = _suggested_projects(str(project["title"])) if not internal_project_id else []
    metadata = {
        "status": project.get("status"),
        "priority": project.get("priority"),
        "period_start": project.get("period_start"),
        "period_end": project.get("period_end"),
        "summary": project.get("summary"),
        "owner_external_ids": project.get("owner_external_ids") or [],
        "blocked_by_external_ids": project.get("blocked_by_external_ids") or [],
        "source_updated_at": project.get("source_updated_at"),
    }
    status = "linked" if internal_project_id else "pending"
    conn.execute(
        "INSERT INTO notion_source_candidates "
        "(provider, external_id, source_type, title, external_url, metadata_json, suggested_project_ids, project_id, status, created_at, updated_at) "
        "VALUES (?, ?, 'project', ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(provider, external_id) DO UPDATE SET title=excluded.title, external_url=excluded.external_url, "
        "metadata_json=excluded.metadata_json, suggested_project_ids=excluded.suggested_project_ids, "
        "project_id=excluded.project_id, status=CASE WHEN notion_source_candidates.status='ignored' AND excluded.project_id IS NULL "
        "THEN 'ignored' ELSE excluded.status END, updated_at=excluded.updated_at",
        (
            _PROVIDER,
            project["external_id"],
            project["title"],
            project.get("url"),
            _json(metadata),
            _json(suggestions),
            internal_project_id,
            status,
            now,
            now,
        ),
    )


def upsert_projects(projects: list[dict[str, Any]]) -> int:
    """Cache Notion projects and create unconfirmed mapping candidates."""
    ensure_notion_project_schema()
    now = db.now_iso()
    with db.get_connection() as conn:
        for project in projects:
            external_id = str(project.get("external_id") or "").strip()
            title = str(project.get("title") or "").strip()
            if not external_id or not title:
                continue
            internal_project_id = _confirmed_internal_project(conn, external_id)
            conn.execute(
                "INSERT INTO notion_projects_cache "
                "(external_id, internal_project_id, title, status, owner_external_ids, priority, period_start, period_end, summary, "
                "task_external_ids, blocked_by_external_ids, url, source_created_at, source_updated_at, synced_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(external_id) DO UPDATE SET internal_project_id=excluded.internal_project_id, title=excluded.title, "
                "status=excluded.status, owner_external_ids=excluded.owner_external_ids, priority=excluded.priority, "
                "period_start=excluded.period_start, period_end=excluded.period_end, summary=excluded.summary, "
                "task_external_ids=excluded.task_external_ids, blocked_by_external_ids=excluded.blocked_by_external_ids, "
                "url=excluded.url, source_created_at=excluded.source_created_at, source_updated_at=excluded.source_updated_at, "
                "synced_at=excluded.synced_at",
                (
                    external_id,
                    internal_project_id,
                    title,
                    project.get("status") or "unknown",
                    _json(project.get("owner_external_ids") or []),
                    project.get("priority"),
                    project.get("period_start"),
                    project.get("period_end"),
                    project.get("summary"),
                    _json(project.get("task_external_ids") or []),
                    _json(project.get("blocked_by_external_ids") or []),
                    project.get("url"),
                    project.get("source_created_at"),
                    project.get("source_updated_at"),
                    now,
                ),
            )
            _upsert_candidate(conn, project, internal_project_id=internal_project_id, now=now)
    return sum(1 for item in projects if item.get("external_id") and item.get("title"))


def _resolve_task_project(conn: Any, external_ids: list[str]) -> str | None:
    resolved = {
        project_id
        for external_id in external_ids
        if (project_id := _confirmed_internal_project(conn, external_id))
    }
    return next(iter(resolved)) if len(resolved) == 1 else None


def upsert_tasks(tasks: list[dict[str, Any]]) -> int:
    """Extend the legacy task cache without losing Notion Relation identities."""
    ensure_notion_project_schema()
    now = db.now_iso()
    count = 0
    with db.get_connection() as conn:
        for task in tasks:
            external_id = str(task.get("external_id") or "").strip()
            title = str(task.get("title") or "").strip()
            if not external_id or not title:
                continue
            project_external_ids = [str(item) for item in task.get("project_external_ids") or [] if str(item).strip()]
            parent_external_ids = [str(item) for item in task.get("parent_external_ids") or [] if str(item).strip()]
            project_id = _resolve_task_project(conn, project_external_ids)
            values = (
                title,
                task.get("status") or "unknown",
                task.get("due_date"),
                task.get("priority"),
                task.get("category"),
                task.get("reason"),
                task.get("url"),
                task.get("done_date"),
                project_external_ids[0] if project_external_ids else None,
                _json(project_external_ids),
                project_id,
                _json(task.get("assignee_external_ids") or []),
                parent_external_ids[0] if parent_external_ids else None,
                _json(parent_external_ids),
                _json(task.get("subtask_external_ids") or []),
                task.get("summary"),
                task.get("source_updated_at"),
                now,
                external_id,
            )
            existing = conn.execute(
                "SELECT id FROM tasks_cache WHERE source='notion' AND external_id=?",
                (external_id,),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE tasks_cache SET title=?, status=?, due_date=?, priority=?, category=?, reason=?, url=?, done_date=?, "
                    "project_external_id=?, project_external_ids=?, project_id=?, assignee_external_ids=?, parent_external_id=?, "
                    "parent_external_ids=?, subtask_external_ids=?, summary=?, source_updated_at=?, updated_at=? "
                    "WHERE source='notion' AND external_id=?",
                    values,
                )
            else:
                conn.execute(
                    "INSERT INTO tasks_cache "
                    "(source, title, status, due_date, priority, category, reason, url, done_date, project_external_id, "
                    "project_external_ids, project_id, assignee_external_ids, parent_external_id, parent_external_ids, "
                    "subtask_external_ids, summary, source_updated_at, updated_at, external_id) "
                    "VALUES ('notion', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    values,
                )
            count += 1
    return count


def _safe_error(exc: Exception) -> str:
    text = str(exc)
    for secret in (config.NOTION_API_KEY, config.NOTION_PROJECTS_DB_ID, config.NOTION_TASKS_DB_ID):
        if secret:
            text = text.replace(secret, "[redacted]")
    return text[:300] or "Notion の同期に失敗しました"


def _cached_count(source: str) -> int:
    ensure_notion_project_schema()
    with db.get_connection() as conn:
        if source == PROJECT_SOURCE:
            return int(conn.execute("SELECT COUNT(*) FROM notion_projects_cache").fetchone()[0])
        return int(conn.execute("SELECT COUNT(*) FROM tasks_cache WHERE source='notion'").fetchone()[0])


def _source_status(source: str, configured: bool) -> dict[str, Any]:
    state = db.sync_state(source)
    cached_count = _cached_count(source)
    return {
        "source": source,
        "configured": configured,
        "ok": bool(state.get("last_success_at") and not state.get("last_failure_at")),
        "cached": cached_count > 0,
        "synced_count": int(state.get("synced_count") or 0),
        "cached_count": cached_count,
        "last_synced_at": state.get("last_success_at"),
        "last_failed_at": state.get("last_failure_at"),
        "stale": bool(state.get("last_failure_at") and state.get("last_success_at")),
        "error": state.get("last_error"),
    }


def _sync_source(
    source: str,
    *,
    configured: bool,
    loader: Callable[[], list[dict[str, Any]]],
    writer: Callable[[list[dict[str, Any]]], int],
    force: bool,
) -> dict[str, Any]:
    if not configured:
        return _source_status(source, False) | {"ok": False, "error": "未設定", "skipped": True}
    last = _last_sync_monotonic.get(source)
    if not force and last is not None and time.monotonic() - last < config.NOTION_SYNC_TTL_SECONDS:
        return _source_status(source, True) | {"ok": True, "cached": True, "skipped": False}
    try:
        count = writer(loader())
        at = db.record_sync_success(source, count)
        _last_sync_monotonic[source] = time.monotonic()
        return {
            "source": source,
            "configured": True,
            "ok": True,
            "cached": False,
            "stale": False,
            "synced_count": count,
            "cached_count": _cached_count(source),
            "last_synced_at": at,
            "last_failed_at": None,
            "error": None,
            "skipped": False,
        }
    except NotionError as exc:
        error = _safe_error(exc)
        db.record_sync_failure(source, error)
        return _source_status(source, True) | {"ok": False, "error": error, "skipped": False}


def sync_all_if_configured(
    force: bool = False,
    *,
    project_loader: Callable[[], list[dict[str, Any]]] | None = None,
    task_loader: Callable[[], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Synchronize project and task sources independently and preserve partial success."""
    ensure_notion_project_schema()
    project_configured = config.notion_projects_configured()
    task_configured = config.notion_configured()
    projects = _sync_source(
        PROJECT_SOURCE,
        configured=project_configured,
        loader=project_loader or query_projects_database,
        writer=upsert_projects,
        force=force,
    )
    tasks = _sync_source(
        TASK_SOURCE,
        configured=task_configured,
        loader=task_loader or query_tasks_database_v2,
        writer=upsert_tasks,
        force=force,
    )
    required = [item for item in (projects, tasks) if item.get("configured")]
    ok = bool(required) and all(item.get("ok") for item in required)
    errors = [f"{item['source']}: {item['error']}" for item in required if item.get("error")]
    # Maintain the legacy aggregate only when the task source succeeds. Existing
    # task-only callers remain compatible while v2 callers inspect `sources`.
    if tasks.get("ok"):
        db.record_sync_success("notion", int(tasks.get("synced_count") or 0))
    elif tasks.get("configured") and tasks.get("error"):
        db.record_sync_failure("notion", str(tasks["error"]))
    return {
        "ok": ok,
        "configured": bool(required),
        "source": "notion",
        "sources": {"projects": projects, "tasks": tasks},
        "synced_count": int(projects.get("synced_count") or 0) + int(tasks.get("synced_count") or 0),
        "synced": int(projects.get("synced_count") or 0) + int(tasks.get("synced_count") or 0),
        "cached": any(item.get("cached") for item in required),
        "stale": any(item.get("stale") for item in required),
        "last_synced_at": max(
            [str(item["last_synced_at"]) for item in required if item.get("last_synced_at")],
            default=None,
        ),
        "error": "; ".join(errors) if errors else None,
        "partial": bool(required) and any(item.get("ok") for item in required) and not ok,
    }


def status() -> dict[str, Any]:
    ensure_notion_project_schema()
    projects = _source_status(PROJECT_SOURCE, config.notion_projects_configured())
    tasks = _source_status(TASK_SOURCE, config.notion_configured())
    configured = [item for item in (projects, tasks) if item.get("configured")]
    return {
        "configured": bool(configured),
        "sources": {"projects": projects, "tasks": tasks},
        "stale": any(item.get("stale") for item in configured),
        "error": "; ".join(
            f"{item['source']}: {item['error']}" for item in configured if item.get("error")
        ) or None,
        "synced_count": sum(int(item.get("synced_count") or 0) for item in configured),
        "last_synced_at": max(
            [str(item["last_synced_at"]) for item in configured if item.get("last_synced_at")],
            default=None,
        ),
    }


def list_source_candidates(status_filter: str = "pending", limit: int = 20) -> list[dict[str, Any]]:
    ensure_notion_project_schema()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM notion_source_candidates WHERE status=? ORDER BY updated_at DESC LIMIT ?",
            (status_filter, max(1, min(limit, 100))),
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for key in ("metadata_json", "suggested_project_ids"):
            try:
                item[key.removesuffix("_json")] = json.loads(str(item.pop(key) or "{}" if key == "metadata_json" else "[]"))
            except json.JSONDecodeError:
                item[key.removesuffix("_json")] = {} if key == "metadata_json" else []
        result.append(item)
    return result
