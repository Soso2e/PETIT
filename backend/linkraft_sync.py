"""Owner-only Linkraft project synchronization for PETIT Phase 2."""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Callable

from . import db, linkraft_config, project_completion, project_continuity
from .linkraft_client import LinkraftError, get_project_snapshot, list_owned_projects

_PROVIDER = "linkraft"
PROJECT_SOURCE = "linkraft:projects"
_last_sync_monotonic: dict[str, float] = {}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS linkraft_projects_cache (
    external_id TEXT PRIMARY KEY,
    internal_project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    description TEXT,
    goal TEXT,
    group_id TEXT,
    visibility TEXT,
    mentor_id TEXT,
    mentor_request_status TEXT,
    deletion_status TEXT,
    color TEXT,
    source_created_at TEXT,
    source_updated_at TEXT,
    synced_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS linkraft_source_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    external_url TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    suggested_project_ids TEXT NOT NULL DEFAULT '[]',
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS linkraft_sync_cursors (
    external_project_id TEXT PRIMARY KEY,
    next_since TEXT,
    last_success_at TEXT,
    last_failure_at TEXT,
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS linkraft_activity_cache (
    external_id TEXT PRIMARY KEY,
    external_project_id TEXT NOT NULL,
    internal_project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
    actor_id TEXT,
    type TEXT NOT NULL,
    text TEXT NOT NULL,
    source_created_at TEXT,
    source_updated_at TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    synced_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_linkraft_activity_project
ON linkraft_activity_cache(internal_project_id, source_updated_at);

CREATE TABLE IF NOT EXISTS linkraft_support_cache (
    external_id TEXT PRIMARY KEY,
    external_project_id TEXT NOT NULL,
    internal_project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
    task_external_id TEXT,
    author_id TEXT,
    kind TEXT NOT NULL,
    body TEXT NOT NULL,
    help_status TEXT,
    assigned_supporter_id TEXT,
    next_action TEXT,
    resolution_summary TEXT,
    source_created_at TEXT,
    source_updated_at TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    synced_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_linkraft_support_project
ON linkraft_support_cache(internal_project_id, help_status, source_updated_at);

CREATE TABLE IF NOT EXISTS linkraft_knowledge_cache (
    external_id TEXT PRIMARY KEY,
    external_project_id TEXT NOT NULL,
    internal_project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    type TEXT,
    description TEXT,
    url TEXT,
    created_by TEXT,
    source_created_at TEXT,
    source_updated_at TEXT,
    synced_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_linkraft_knowledge_project
ON linkraft_knowledge_cache(internal_project_id, source_updated_at);
"""

_TASK_COLUMNS = {
    "project_external_id": "TEXT",
    "project_external_ids": "TEXT NOT NULL DEFAULT '[]'",
    "project_id": "TEXT",
    "assignee_external_ids": "TEXT NOT NULL DEFAULT '[]'",
    "summary": "TEXT",
    "source_updated_at": "TEXT",
}


def _ensure_columns(conn: Any, table: str, columns: dict[str, str]) -> None:
    existing = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}')


def ensure_linkraft_schema() -> None:
    project_completion.ensure_completion_schema()
    with db.get_connection() as conn:
        conn.executescript(_SCHEMA)
        _ensure_columns(conn, "tasks_cache", _TASK_COLUMNS)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_linkraft_task_project ON tasks_cache(source, project_id, status)")


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def _confirmed_project(conn: Any, external_id: str) -> str | None:
    row = conn.execute(
        "SELECT project_id FROM project_source_links WHERE provider='linkraft' AND external_id=? "
        "AND status='active' AND confirmed_at IS NOT NULL",
        (external_id,),
    ).fetchone()
    return str(row["project_id"]) if row else None


def _suggestions(name: str) -> list[str]:
    return [str(item["id"]) for item in project_continuity.find_projects_by_alias(name)]


def upsert_owned_projects(projects: list[dict[str, Any]]) -> int:
    """Cache the owner-scoped project list and create unconfirmed candidates."""
    ensure_linkraft_schema()
    now = db.now_iso()
    count = 0
    with db.get_connection() as conn:
        for project in projects:
            external_id = str(project.get("id") or "").strip()
            name = str(project.get("name") or "").strip()
            if not external_id or not name:
                continue
            internal_id = _confirmed_project(conn, external_id)
            conn.execute(
                "INSERT INTO linkraft_projects_cache "
                "(external_id, internal_project_id, name, description, goal, group_id, visibility, mentor_id, mentor_request_status, "
                "deletion_status, color, source_created_at, source_updated_at, synced_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(external_id) DO UPDATE SET internal_project_id=excluded.internal_project_id, name=excluded.name, "
                "description=excluded.description, goal=excluded.goal, group_id=excluded.group_id, visibility=excluded.visibility, "
                "mentor_id=excluded.mentor_id, mentor_request_status=excluded.mentor_request_status, "
                "deletion_status=excluded.deletion_status, color=excluded.color, source_created_at=excluded.source_created_at, "
                "source_updated_at=excluded.source_updated_at, synced_at=excluded.synced_at",
                (
                    external_id,
                    internal_id,
                    name,
                    project.get("description"),
                    project.get("goal"),
                    project.get("groupId"),
                    project.get("visibility"),
                    project.get("mentorId"),
                    project.get("mentorRequestStatus"),
                    project.get("deletionStatus"),
                    project.get("color"),
                    project.get("createdAt"),
                    project.get("updatedAt"),
                    now,
                ),
            )
            metadata = {
                key: project.get(key)
                for key in (
                    "description",
                    "goal",
                    "groupId",
                    "visibility",
                    "mentorId",
                    "mentorRequestStatus",
                    "deletionStatus",
                    "color",
                    "createdAt",
                    "updatedAt",
                )
            }
            suggestions = [] if internal_id else _suggestions(name)
            conn.execute(
                "INSERT INTO linkraft_source_candidates "
                "(external_id, name, external_url, metadata_json, suggested_project_ids, project_id, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(external_id) DO UPDATE SET name=excluded.name, metadata_json=excluded.metadata_json, "
                "suggested_project_ids=excluded.suggested_project_ids, project_id=excluded.project_id, "
                "status=CASE WHEN linkraft_source_candidates.status='ignored' AND excluded.project_id IS NULL "
                "THEN 'ignored' ELSE excluded.status END, updated_at=excluded.updated_at",
                (
                    external_id,
                    name,
                    None,
                    _json(metadata),
                    json.dumps(suggestions, ensure_ascii=False),
                    internal_id,
                    "linked" if internal_id else "pending",
                    now,
                    now,
                ),
            )
            count += 1
    return count


def _event_key(kind: str, external_id: str, updated_at: str | None) -> str:
    source = f"linkraft|{kind}|{external_id}|{updated_at or ''}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _insert_event(
    conn: Any,
    *,
    project_id: str,
    kind: str,
    external_id: str,
    summary: str,
    occurred_at: str | None,
    payload: dict[str, Any],
) -> None:
    now = db.now_iso()
    conn.execute(
        "INSERT OR IGNORE INTO project_events "
        "(project_id, provider, event_type, summary, payload_json, idempotency_key, occurred_at, created_at) "
        "VALUES (?, 'linkraft', ?, ?, ?, ?, ?, ?)",
        (
            project_id,
            kind,
            summary[:500],
            _json(payload),
            _event_key(kind, external_id, occurred_at),
            occurred_at or now,
            now,
        ),
    )


def _upsert_task(conn: Any, task: dict[str, Any], external_project_id: str, project_id: str, now: str) -> None:
    external_id = str(task.get("id") or "").strip()
    title = str(task.get("title") or "").strip()
    if not external_id or not title:
        return
    status = str(task.get("status") or "これから")
    assignee_ids = [str(task["assigneeId"])] if task.get("assigneeId") else []
    values = (
        title,
        status,
        task.get("due"),
        None,
        "Linkraft",
        None,
        None,
        None,
        external_project_id,
        json.dumps([external_project_id], ensure_ascii=False),
        project_id,
        json.dumps(assignee_ids, ensure_ascii=False),
        None,
        task.get("updatedAt"),
        now,
        external_id,
    )
    existing = conn.execute(
        "SELECT id FROM tasks_cache WHERE source='linkraft' AND external_id=?",
        (external_id,),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE tasks_cache SET title=?, status=?, due_date=?, priority=?, category=?, reason=?, url=?, done_date=?, "
            "project_external_id=?, project_external_ids=?, project_id=?, assignee_external_ids=?, summary=?, "
            "source_updated_at=?, updated_at=? WHERE source='linkraft' AND external_id=?",
            values,
        )
    else:
        conn.execute(
            "INSERT INTO tasks_cache "
            "(source, title, status, due_date, priority, category, reason, url, done_date, project_external_id, "
            "project_external_ids, project_id, assignee_external_ids, summary, source_updated_at, updated_at, external_id) "
            "VALUES ('linkraft', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            values,
        )
    _insert_event(
        conn,
        project_id=project_id,
        kind=f"task_{status}",
        external_id=external_id,
        summary=f"Linkraftタスク「{title}」は{status}",
        occurred_at=task.get("updatedAt") or task.get("createdAt"),
        payload=task,
    )


def _upsert_activity(conn: Any, item: dict[str, Any], external_project_id: str, project_id: str, now: str) -> None:
    external_id = str(item.get("id") or "").strip()
    text = str(item.get("text") or "").strip()
    if not external_id or not text:
        return
    conn.execute(
        "INSERT INTO linkraft_activity_cache "
        "(external_id, external_project_id, internal_project_id, actor_id, type, text, source_created_at, source_updated_at, payload_json, synced_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(external_id) DO UPDATE SET internal_project_id=excluded.internal_project_id, actor_id=excluded.actor_id, "
        "type=excluded.type, text=excluded.text, source_created_at=excluded.source_created_at, "
        "source_updated_at=excluded.source_updated_at, payload_json=excluded.payload_json, synced_at=excluded.synced_at",
        (
            external_id,
            external_project_id,
            project_id,
            item.get("actorId"),
            item.get("type") or "activity",
            text,
            item.get("createdAt"),
            item.get("updatedAt"),
            _json(item),
            now,
        ),
    )
    _insert_event(
        conn,
        project_id=project_id,
        kind=f"activity_{item.get('type') or 'activity'}",
        external_id=external_id,
        summary=text,
        occurred_at=item.get("updatedAt") or item.get("createdAt"),
        payload=item,
    )


def _upsert_support(conn: Any, item: dict[str, Any], external_project_id: str, project_id: str, now: str) -> None:
    external_id = str(item.get("id") or "").strip()
    body = str(item.get("body") or "").strip()
    if not external_id or not body:
        return
    conn.execute(
        "INSERT INTO linkraft_support_cache "
        "(external_id, external_project_id, internal_project_id, task_external_id, author_id, kind, body, help_status, "
        "assigned_supporter_id, next_action, resolution_summary, source_created_at, source_updated_at, payload_json, synced_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(external_id) DO UPDATE SET internal_project_id=excluded.internal_project_id, task_external_id=excluded.task_external_id, "
        "author_id=excluded.author_id, kind=excluded.kind, body=excluded.body, help_status=excluded.help_status, "
        "assigned_supporter_id=excluded.assigned_supporter_id, next_action=excluded.next_action, "
        "resolution_summary=excluded.resolution_summary, source_created_at=excluded.source_created_at, "
        "source_updated_at=excluded.source_updated_at, payload_json=excluded.payload_json, synced_at=excluded.synced_at",
        (
            external_id,
            external_project_id,
            project_id,
            item.get("taskId"),
            item.get("authorId"),
            item.get("kind") or "other",
            body,
            item.get("helpStatus"),
            item.get("assignedSupporterId"),
            item.get("nextAction"),
            item.get("resolutionSummary"),
            item.get("createdAt"),
            item.get("updatedAt"),
            _json(item),
            now,
        ),
    )
    status = item.get("helpStatus") or "open"
    summary = str(item.get("resolutionSummary") or item.get("nextAction") or body)
    _insert_event(
        conn,
        project_id=project_id,
        kind=f"support_{item.get('kind') or 'other'}_{status}",
        external_id=external_id,
        summary=summary,
        occurred_at=item.get("updatedAt") or item.get("createdAt"),
        payload=item,
    )


def _upsert_knowledge(conn: Any, item: dict[str, Any], external_project_id: str, project_id: str, now: str) -> None:
    external_id = str(item.get("id") or "").strip()
    title = str(item.get("title") or "").strip()
    if not external_id or not title:
        return
    conn.execute(
        "INSERT INTO linkraft_knowledge_cache "
        "(external_id, external_project_id, internal_project_id, title, type, description, url, created_by, "
        "source_created_at, source_updated_at, synced_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(external_id) DO UPDATE SET internal_project_id=excluded.internal_project_id, title=excluded.title, "
        "type=excluded.type, description=excluded.description, url=excluded.url, created_by=excluded.created_by, "
        "source_created_at=excluded.source_created_at, source_updated_at=excluded.source_updated_at, synced_at=excluded.synced_at",
        (
            external_id,
            external_project_id,
            project_id,
            title,
            item.get("type"),
            item.get("description"),
            item.get("url"),
            item.get("createdBy"),
            item.get("createdAt"),
            item.get("updatedAt"),
            now,
        ),
    )
    _insert_event(
        conn,
        project_id=project_id,
        kind="knowledge_updated",
        external_id=external_id,
        summary=f"Linkraftナレッジ「{title}」が更新された",
        occurred_at=item.get("updatedAt") or item.get("createdAt"),
        payload=item,
    )


def apply_snapshot(snapshot: dict[str, Any], project_id: str) -> dict[str, Any]:
    ensure_linkraft_schema()
    project = snapshot.get("project") or {}
    external_project_id = str(project.get("id") or "").strip()
    if not external_project_id:
        raise LinkraftError("Linkraft snapshot has no project id")
    now = db.now_iso()
    tasks = [item for item in snapshot.get("tasks") or [] if isinstance(item, dict)]
    activities = [item for item in snapshot.get("activities") or [] if isinstance(item, dict)]
    support = [item for item in snapshot.get("supportPosts") or [] if isinstance(item, dict)]
    knowledge = [item for item in snapshot.get("knowledge") or [] if isinstance(item, dict)]
    with db.get_connection() as conn:
        for item in tasks:
            _upsert_task(conn, item, external_project_id, project_id, now)
        for item in activities:
            _upsert_activity(conn, item, external_project_id, project_id, now)
        for item in support:
            _upsert_support(conn, item, external_project_id, project_id, now)
        for item in knowledge:
            _upsert_knowledge(conn, item, external_project_id, project_id, now)
        if snapshot.get("fullSnapshot"):
            task_ids = [str(item.get("id")) for item in tasks if item.get("id")]
            if task_ids:
                placeholders = ",".join("?" for _ in task_ids)
                conn.execute(
                    f"DELETE FROM tasks_cache WHERE source='linkraft' AND project_external_id=? AND external_id NOT IN ({placeholders})",
                    (external_project_id, *task_ids),
                )
            else:
                conn.execute(
                    "DELETE FROM tasks_cache WHERE source='linkraft' AND project_external_id=?",
                    (external_project_id,),
                )
        conn.execute(
            "INSERT INTO linkraft_sync_cursors (external_project_id, next_since, last_success_at, last_failure_at, last_error) "
            "VALUES (?, ?, ?, NULL, NULL) ON CONFLICT(external_project_id) DO UPDATE SET "
            "next_since=excluded.next_since, last_success_at=excluded.last_success_at, last_failure_at=NULL, last_error=NULL",
            (external_project_id, snapshot.get("nextSince"), now),
        )
    return {
        "external_project_id": external_project_id,
        "project_id": project_id,
        "next_since": snapshot.get("nextSince"),
        "counts": {
            "tasks": len(tasks),
            "activities": len(activities),
            "support": len(support),
            "knowledge": len(knowledge),
        },
    }


def _cursor(external_project_id: str) -> str | None:
    ensure_linkraft_schema()
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT next_since FROM linkraft_sync_cursors WHERE external_project_id=?",
            (external_project_id,),
        ).fetchone()
    return str(row["next_since"]) if row and row["next_since"] else None


def _confirmed_links() -> list[dict[str, str]]:
    ensure_linkraft_schema()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT external_id, project_id FROM project_source_links WHERE provider='linkraft' "
            "AND status='active' AND confirmed_at IS NOT NULL ORDER BY external_id"
        ).fetchall()
    return [{"external_id": str(row["external_id"]), "project_id": str(row["project_id"])} for row in rows]


def _safe_error(exc: Exception) -> str:
    text = str(exc)
    if linkraft_config.READ_TOKEN:
        text = text.replace(linkraft_config.READ_TOKEN, "[redacted]")
    return text[:300] or "Linkraft sync failed"


def sync_if_configured(
    force: bool = False,
    *,
    project_loader: Callable[[], list[dict[str, Any]]] | None = None,
    snapshot_loader: Callable[[str, str | None], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ensure_linkraft_schema()
    if not linkraft_config.configured() and project_loader is None:
        return {"ok": False, "configured": False, "source": "linkraft", "error": "未設定", "projects": [], "stale": False}
    last = _last_sync_monotonic.get(PROJECT_SOURCE)
    if not force and last is not None and time.monotonic() - last < linkraft_config.SYNC_TTL_SECONDS:
        state = db.sync_state(PROJECT_SOURCE)
        return {"ok": True, "configured": True, "source": "linkraft", "cached": True, "stale": False, "projects": [], "last_synced_at": state.get("last_success_at")}

    load_projects = project_loader or list_owned_projects
    load_snapshot = snapshot_loader or get_project_snapshot
    try:
        project_count = upsert_owned_projects(load_projects())
        projects_at = db.record_sync_success(PROJECT_SOURCE, project_count)
        _last_sync_monotonic[PROJECT_SOURCE] = time.monotonic()
    except LinkraftError as exc:
        error = _safe_error(exc)
        db.record_sync_failure(PROJECT_SOURCE, error)
        state = db.sync_state(PROJECT_SOURCE)
        return {
            "ok": False,
            "configured": True,
            "source": "linkraft",
            "error": error,
            "stale": bool(state.get("last_success_at")),
            "projects": [],
        }

    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for link in _confirmed_links():
        source = f"linkraft:project:{link['external_id']}"
        try:
            result = apply_snapshot(
                load_snapshot(link["external_id"], _cursor(link["external_id"])),
                link["project_id"],
            )
            total = sum(int(value) for value in result["counts"].values())
            db.record_sync_success(source, total)
            results.append(result | {"ok": True})
        except LinkraftError as exc:
            error = _safe_error(exc)
            db.record_sync_failure(source, error)
            with db.get_connection() as conn:
                conn.execute(
                    "INSERT INTO linkraft_sync_cursors (external_project_id, last_failure_at, last_error) VALUES (?, ?, ?) "
                    "ON CONFLICT(external_project_id) DO UPDATE SET last_failure_at=excluded.last_failure_at, last_error=excluded.last_error",
                    (link["external_id"], db.now_iso(), error),
                )
            errors.append(f"{link['external_id']}: {error}")
            results.append({"ok": False, "external_project_id": link["external_id"], "project_id": link["project_id"], "error": error})
    ok = not errors
    return {
        "ok": ok,
        "configured": True,
        "source": "linkraft",
        "project_count": project_count,
        "projects": results,
        "partial": bool(errors and any(item.get("ok") for item in results)),
        "stale": any(
            db.sync_state(f"linkraft:project:{link['external_id']}").get("last_success_at")
            for link in _confirmed_links()
            if any(item.get("external_project_id") == link["external_id"] and not item.get("ok") for item in results)
        ),
        "last_synced_at": projects_at,
        "error": "; ".join(errors) if errors else None,
    }
