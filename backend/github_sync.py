"""Read-only GitHub repository evidence synchronization for PETIT.

GitHub facts are stored as project-scoped evidence. They never mutate PETIT's
completion checkpoint: a commit, successful check, merge, or deployment each proves
only its own event type.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable

from . import db, github_config, project_completion, project_continuity
from .github_client import GitHubEvidenceError, get_repository, get_repository_evidence, normalize_repository

_PROVIDER = "github"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS github_repositories_cache (
    full_name TEXT PRIMARY KEY COLLATE NOCASE,
    internal_project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    repository_id TEXT,
    name TEXT NOT NULL,
    owner_login TEXT,
    default_branch TEXT,
    private INTEGER NOT NULL DEFAULT 0,
    visibility TEXT,
    description TEXT,
    html_url TEXT,
    pushed_at TEXT,
    source_updated_at TEXT,
    synced_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_github_repositories_project
ON github_repositories_cache(internal_project_id, source_updated_at);

CREATE TABLE IF NOT EXISTS github_repository_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name TEXT NOT NULL,
    html_url TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    suggested_project_ids TEXT NOT NULL DEFAULT '[]',
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_github_candidates_status
ON github_repository_candidates(status, updated_at);

CREATE TABLE IF NOT EXISTS github_sync_cursors (
    full_name TEXT PRIMARY KEY COLLATE NOCASE,
    next_since TEXT,
    last_success_at TEXT,
    last_failure_at TEXT,
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS github_evidence_cache (
    repository_full_name TEXT NOT NULL COLLATE NOCASE,
    evidence_type TEXT NOT NULL,
    external_id TEXT NOT NULL,
    internal_project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
    headline TEXT NOT NULL,
    state TEXT,
    sha TEXT,
    ref TEXT,
    url TEXT,
    occurred_at TEXT,
    source_updated_at TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    synced_at TEXT NOT NULL,
    PRIMARY KEY (repository_full_name, evidence_type, external_id)
);
CREATE INDEX IF NOT EXISTS idx_github_evidence_project_time
ON github_evidence_cache(internal_project_id, occurred_at);
"""

_FINAL_CHECK_FAILURES = {
    "failure",
    "timed_out",
    "action_required",
    "startup_failure",
}
_DEPLOYMENT_FAILURES = {"failure", "error"}


def ensure_github_schema() -> None:
    project_completion.ensure_completion_schema()
    with db.get_connection() as conn:
        conn.executescript(_SCHEMA)


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def _confirmed_project(conn: Any, full_name: str) -> str | None:
    row = conn.execute(
        "SELECT project_id FROM project_source_links WHERE provider='github' "
        "AND lower(external_id)=lower(?) AND status='active' AND confirmed_at IS NOT NULL",
        (full_name,),
    ).fetchone()
    return str(row["project_id"]) if row else None


def _suggestions(metadata: dict[str, Any]) -> list[str]:
    values = [str(metadata.get("name") or ""), str(metadata.get("full_name") or "")]
    result: list[str] = []
    for value in values:
        for project in project_continuity.find_projects_by_alias(value):
            project_id = str(project["id"])
            if project_id not in result:
                result.append(project_id)
    return result


def _metadata_fields(metadata: dict[str, Any]) -> dict[str, Any]:
    owner = metadata.get("owner") if isinstance(metadata.get("owner"), dict) else {}
    return {
        "repository_id": str(metadata.get("id") or "") or None,
        "name": str(metadata.get("name") or "").strip(),
        "full_name": normalize_repository(str(metadata.get("full_name") or "")),
        "owner_login": str(owner.get("login") or "") or None,
        "default_branch": str(metadata.get("default_branch") or "") or None,
        "private": bool(metadata.get("private")),
        "visibility": metadata.get("visibility"),
        "description": metadata.get("description"),
        "html_url": metadata.get("html_url"),
        "pushed_at": metadata.get("pushed_at"),
        "source_updated_at": metadata.get("updated_at"),
    }


def upsert_repository_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Cache repository metadata and create an unconfirmed mapping candidate."""
    ensure_github_schema()
    fields = _metadata_fields(metadata)
    if not fields["name"]:
        raise GitHubEvidenceError("GitHub repository has no name")
    now = db.now_iso()
    with db.get_connection() as conn:
        project_id = _confirmed_project(conn, fields["full_name"])
        conn.execute(
            "INSERT INTO github_repositories_cache "
            "(full_name, internal_project_id, repository_id, name, owner_login, default_branch, private, visibility, "
            "description, html_url, pushed_at, source_updated_at, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(full_name) DO UPDATE SET internal_project_id=excluded.internal_project_id, "
            "repository_id=excluded.repository_id, name=excluded.name, owner_login=excluded.owner_login, "
            "default_branch=excluded.default_branch, private=excluded.private, visibility=excluded.visibility, "
            "description=excluded.description, html_url=excluded.html_url, pushed_at=excluded.pushed_at, "
            "source_updated_at=excluded.source_updated_at, synced_at=excluded.synced_at",
            (
                fields["full_name"],
                project_id,
                fields["repository_id"],
                fields["name"],
                fields["owner_login"],
                fields["default_branch"],
                int(fields["private"]),
                fields["visibility"],
                fields["description"],
                fields["html_url"],
                fields["pushed_at"],
                fields["source_updated_at"],
                now,
            ),
        )
        suggestions = [] if project_id else _suggestions(metadata)
        candidate_metadata = {
            key: fields[key]
            for key in (
                "repository_id",
                "owner_login",
                "default_branch",
                "private",
                "visibility",
                "description",
                "pushed_at",
                "source_updated_at",
            )
        }
        conn.execute(
            "INSERT INTO github_repository_candidates "
            "(full_name, name, html_url, metadata_json, suggested_project_ids, project_id, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(full_name) DO UPDATE SET name=excluded.name, html_url=excluded.html_url, "
            "metadata_json=excluded.metadata_json, suggested_project_ids=excluded.suggested_project_ids, "
            "project_id=excluded.project_id, status=CASE WHEN github_repository_candidates.status='ignored' "
            "AND excluded.project_id IS NULL THEN 'ignored' ELSE excluded.status END, updated_at=excluded.updated_at",
            (
                fields["full_name"],
                fields["name"],
                fields["html_url"],
                _json(candidate_metadata),
                json.dumps(suggestions, ensure_ascii=False),
                project_id,
                "linked" if project_id else "pending",
                now,
                now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM github_repository_candidates WHERE lower(full_name)=lower(?)",
            (fields["full_name"],),
        ).fetchone()
    return dict(row) if row else {}


def inspect_repository(
    repository: str,
    *,
    repository_loader: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if repository_loader is None and not github_config.configured():
        return {"ok": False, "configured": False, "error": "GitHub token is not configured"}
    loader = repository_loader or get_repository
    try:
        candidate = upsert_repository_metadata(loader(normalize_repository(repository)))
        return {"ok": True, "configured": True, "candidate": candidate}
    except Exception as exc:
        return {"ok": False, "configured": True, "error": safe_error(exc)}


def _event_key(repository: str, event_type: str, external_id: str) -> str:
    value = f"github|{repository.casefold()}|{event_type}|{external_id}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _insert_event(
    conn: Any,
    *,
    project_id: str,
    repository: str,
    event_type: str,
    external_id: str,
    summary: str,
    occurred_at: str | None,
    payload: dict[str, Any],
) -> None:
    now = db.now_iso()
    conn.execute(
        "INSERT OR IGNORE INTO project_events "
        "(project_id, provider, event_type, summary, payload_json, idempotency_key, occurred_at, created_at) "
        "VALUES (?, 'github', ?, ?, ?, ?, ?, ?)",
        (
            project_id,
            event_type,
            summary[:500],
            _json(payload),
            _event_key(repository, event_type, external_id),
            occurred_at or now,
            now,
        ),
    )


def _upsert_evidence(
    conn: Any,
    *,
    repository: str,
    project_id: str,
    evidence_type: str,
    external_id: str,
    headline: str,
    state: str | None,
    sha: str | None,
    ref: str | None,
    url: str | None,
    occurred_at: str | None,
    source_updated_at: str | None,
    payload: dict[str, Any],
    event_type: str | None = None,
    event_summary: str | None = None,
) -> None:
    now = db.now_iso()
    conn.execute(
        "INSERT INTO github_evidence_cache "
        "(repository_full_name, evidence_type, external_id, internal_project_id, headline, state, sha, ref, url, "
        "occurred_at, source_updated_at, payload_json, synced_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(repository_full_name, evidence_type, external_id) DO UPDATE SET "
        "internal_project_id=excluded.internal_project_id, headline=excluded.headline, state=excluded.state, "
        "sha=excluded.sha, ref=excluded.ref, url=excluded.url, occurred_at=excluded.occurred_at, "
        "source_updated_at=excluded.source_updated_at, payload_json=excluded.payload_json, synced_at=excluded.synced_at",
        (
            repository,
            evidence_type,
            external_id,
            project_id,
            headline[:500],
            state,
            sha,
            ref,
            url,
            occurred_at,
            source_updated_at,
            _json(payload),
            now,
        ),
    )
    if event_type:
        _insert_event(
            conn,
            project_id=project_id,
            repository=repository,
            event_type=event_type,
            external_id=external_id,
            summary=event_summary or headline,
            occurred_at=occurred_at or source_updated_at,
            payload=payload,
        )


def _commit_fields(item: dict[str, Any]) -> dict[str, Any]:
    commit = item.get("commit") if isinstance(item.get("commit"), dict) else {}
    author = commit.get("author") if isinstance(commit.get("author"), dict) else {}
    committer = commit.get("committer") if isinstance(commit.get("committer"), dict) else {}
    message = str(commit.get("message") or "").strip()
    return {
        "sha": str(item.get("sha") or "").strip(),
        "headline": message.splitlines()[0] if message else "Commit",
        "author": author.get("name"),
        "occurred_at": committer.get("date") or author.get("date"),
        "url": item.get("html_url"),
    }


def _apply_commit(conn: Any, item: dict[str, Any], repository: str, project_id: str) -> bool:
    fields = _commit_fields(item)
    if not fields["sha"]:
        return False
    _upsert_evidence(
        conn,
        repository=repository,
        project_id=project_id,
        evidence_type="commit",
        external_id=fields["sha"],
        headline=fields["headline"],
        state="recorded",
        sha=fields["sha"],
        ref=None,
        url=fields["url"],
        occurred_at=fields["occurred_at"],
        source_updated_at=fields["occurred_at"],
        payload=item,
        event_type="commit_pushed",
        event_summary=f"GitHub commit {fields['sha'][:7]}: {fields['headline']}",
    )
    return True


def _apply_pull_request(conn: Any, item: dict[str, Any], repository: str, project_id: str) -> bool:
    number = item.get("number")
    title = str(item.get("title") or "").strip()
    if number is None or not title:
        return False
    merged_at = item.get("merged_at")
    state = "merged" if merged_at else str(item.get("state") or "unknown")
    if state == "merged":
        event_type = "pull_request_merged"
    elif state == "open":
        event_type = "pull_request_opened"
    else:
        event_type = "pull_request_closed"
    head = item.get("head") if isinstance(item.get("head"), dict) else {}
    base = item.get("base") if isinstance(item.get("base"), dict) else {}
    ref = f"{head.get('ref') or '?'} -> {base.get('ref') or '?'}"
    occurred_at = merged_at or item.get("closed_at") or item.get("created_at")
    _upsert_evidence(
        conn,
        repository=repository,
        project_id=project_id,
        evidence_type="pull_request",
        external_id=str(number),
        headline=title,
        state=state,
        sha=head.get("sha"),
        ref=ref,
        url=item.get("html_url"),
        occurred_at=occurred_at,
        source_updated_at=item.get("updated_at"),
        payload=item,
        event_type=event_type,
        event_summary=f"GitHub PR #{number} {state}: {title}",
    )
    return True


def _check_event_type(state: str) -> str | None:
    if state == "success":
        return "check_succeeded"
    if state in _FINAL_CHECK_FAILURES:
        return "check_failed"
    if state == "cancelled":
        return "check_cancelled"
    return None


def _apply_check(conn: Any, item: dict[str, Any], repository: str, project_id: str) -> bool:
    check_id = item.get("id")
    name = str(item.get("name") or "").strip()
    if check_id is None or not name:
        return False
    state = str(item.get("conclusion") or item.get("status") or "unknown")
    event_type = _check_event_type(state)
    sha = str(item.get("commit_sha") or item.get("head_sha") or "") or None
    occurred_at = item.get("completed_at") or item.get("started_at")
    _upsert_evidence(
        conn,
        repository=repository,
        project_id=project_id,
        evidence_type="check_run",
        external_id=str(check_id),
        headline=name,
        state=state,
        sha=sha,
        ref=None,
        url=item.get("html_url"),
        occurred_at=occurred_at,
        source_updated_at=item.get("completed_at") or item.get("started_at"),
        payload=item,
        event_type=event_type,
        event_summary=f"GitHub check {state}: {name}",
    )
    return True


def _deployment_event_type(state: str) -> str | None:
    if state == "success":
        return "deployment_succeeded"
    if state in _DEPLOYMENT_FAILURES:
        return "deployment_failed"
    return None


def _apply_deployment(conn: Any, item: dict[str, Any], repository: str, project_id: str) -> bool:
    deployment_id = item.get("id")
    if deployment_id is None:
        return False
    latest = item.get("latest_status") if isinstance(item.get("latest_status"), dict) else {}
    state = str(latest.get("state") or "created")
    status_id = latest.get("id")
    external_id = f"{deployment_id}:{status_id if status_id is not None else state}"
    environment = str(item.get("environment") or latest.get("environment") or "deployment")
    url = latest.get("environment_url") or latest.get("target_url") or latest.get("log_url")
    occurred_at = latest.get("updated_at") or latest.get("created_at") or item.get("updated_at") or item.get("created_at")
    _upsert_evidence(
        conn,
        repository=repository,
        project_id=project_id,
        evidence_type="deployment",
        external_id=external_id,
        headline=environment,
        state=state,
        sha=str(item.get("sha") or "") or None,
        ref=str(item.get("ref") or "") or None,
        url=url,
        occurred_at=occurred_at,
        source_updated_at=occurred_at,
        payload=item,
        event_type=_deployment_event_type(state),
        event_summary=f"GitHub deployment {state}: {environment}",
    )
    return True


def apply_snapshot(snapshot: dict[str, Any], project_id: str) -> dict[str, Any]:
    ensure_github_schema()
    repository_metadata = snapshot.get("repository")
    if not isinstance(repository_metadata, dict):
        raise GitHubEvidenceError("GitHub snapshot has no repository metadata")
    fields = _metadata_fields(repository_metadata)
    repository = fields["full_name"]
    now = db.now_iso()
    counts = {"commits": 0, "pull_requests": 0, "check_runs": 0, "deployments": 0}
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO github_repositories_cache "
            "(full_name, internal_project_id, repository_id, name, owner_login, default_branch, private, visibility, "
            "description, html_url, pushed_at, source_updated_at, synced_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(full_name) DO UPDATE SET internal_project_id=excluded.internal_project_id, "
            "repository_id=excluded.repository_id, name=excluded.name, owner_login=excluded.owner_login, "
            "default_branch=excluded.default_branch, private=excluded.private, visibility=excluded.visibility, "
            "description=excluded.description, html_url=excluded.html_url, pushed_at=excluded.pushed_at, "
            "source_updated_at=excluded.source_updated_at, synced_at=excluded.synced_at",
            (
                repository,
                project_id,
                fields["repository_id"],
                fields["name"],
                fields["owner_login"],
                fields["default_branch"],
                int(fields["private"]),
                fields["visibility"],
                fields["description"],
                fields["html_url"],
                fields["pushed_at"],
                fields["source_updated_at"],
                now,
            ),
        )
        for item in snapshot.get("commits") or []:
            if isinstance(item, dict) and _apply_commit(conn, item, repository, project_id):
                counts["commits"] += 1
        for item in snapshot.get("pullRequests") or []:
            if isinstance(item, dict) and _apply_pull_request(conn, item, repository, project_id):
                counts["pull_requests"] += 1
        for item in snapshot.get("checkRuns") or []:
            if isinstance(item, dict) and _apply_check(conn, item, repository, project_id):
                counts["check_runs"] += 1
        for item in snapshot.get("deployments") or []:
            if isinstance(item, dict) and _apply_deployment(conn, item, repository, project_id):
                counts["deployments"] += 1
        conn.execute(
            "INSERT INTO github_sync_cursors (full_name, next_since, last_success_at, last_failure_at, last_error) "
            "VALUES (?, ?, ?, NULL, NULL) ON CONFLICT(full_name) DO UPDATE SET "
            "next_since=excluded.next_since, last_success_at=excluded.last_success_at, last_failure_at=NULL, last_error=NULL",
            (repository, snapshot.get("nextSince"), now),
        )
    return {
        "repository": repository,
        "project_id": project_id,
        "next_since": snapshot.get("nextSince"),
        "counts": counts,
    }


def cursor(full_name: str) -> str | None:
    ensure_github_schema()
    repository = normalize_repository(full_name)
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT next_since FROM github_sync_cursors WHERE lower(full_name)=lower(?)",
            (repository,),
        ).fetchone()
    return str(row["next_since"]) if row and row["next_since"] else None


def safe_error(exc: Exception) -> str:
    text = str(exc)
    if github_config.TOKEN:
        text = text.replace(github_config.TOKEN, "[redacted]")
    return text[:300] or "GitHub evidence sync failed"


def _record_failure(full_name: str, error: str) -> None:
    ensure_github_schema()
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO github_sync_cursors (full_name, last_failure_at, last_error) VALUES (?, ?, ?) "
            "ON CONFLICT(full_name) DO UPDATE SET last_failure_at=excluded.last_failure_at, last_error=excluded.last_error",
            (normalize_repository(full_name), db.now_iso(), error),
        )


def _fresh_enough(source: str) -> bool:
    state = db.sync_state(source)
    success = state.get("last_success_at")
    failure = state.get("last_failure_at")
    if not success or (failure and str(failure) >= str(success)):
        return False
    try:
        parsed = datetime.fromisoformat(str(success).replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - parsed).total_seconds() < github_config.SYNC_TTL_SECONDS


def refresh_repository_link(
    project_id: str,
    repository: str,
    *,
    force: bool = False,
    snapshot_loader: Callable[[str, str | None], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    full_name = normalize_repository(repository)
    source = f"github:repo:{full_name.casefold()}"
    if snapshot_loader is None and not github_config.configured():
        return {
            "provider": "github",
            "source": source,
            "repository": full_name,
            "ok": False,
            "configured": False,
            "skipped": True,
            "stale": bool(db.sync_state(source).get("last_success_at")),
            "error": "未設定",
        }
    if not force and _fresh_enough(source):
        state = db.sync_state(source)
        return {
            "provider": "github",
            "source": source,
            "repository": full_name,
            "ok": True,
            "configured": True,
            "skipped": False,
            "cached": True,
            "stale": False,
            "last_synced_at": state.get("last_success_at"),
            "error": None,
        }
    loader = snapshot_loader or get_repository_evidence
    try:
        applied = apply_snapshot(loader(full_name, cursor(full_name)), project_id)
        count = sum(int(value) for value in applied["counts"].values())
        synced_at = db.record_sync_success(source, count)
        return {
            "provider": "github",
            "source": source,
            "repository": full_name,
            "ok": True,
            "configured": True,
            "skipped": False,
            "cached": False,
            "stale": False,
            "last_synced_at": synced_at,
            "error": None,
            "result": applied,
        }
    except Exception as exc:
        error = safe_error(exc)
        db.record_sync_failure(source, error)
        _record_failure(full_name, error)
        state = db.sync_state(source)
        return {
            "provider": "github",
            "source": source,
            "repository": full_name,
            "ok": False,
            "configured": True,
            "skipped": False,
            "cached": bool(state.get("last_success_at")),
            "stale": bool(state.get("last_success_at")),
            "last_synced_at": state.get("last_success_at"),
            "error": error,
        }


def confirmed_repository_links() -> list[dict[str, str]]:
    ensure_github_schema()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT external_id, project_id FROM project_source_links WHERE provider='github' "
            "AND status='active' AND confirmed_at IS NOT NULL ORDER BY external_id"
        ).fetchall()
    return [
        {"repository": str(row["external_id"]), "project_id": str(row["project_id"])}
        for row in rows
    ]


def sync_if_configured(
    force: bool = False,
    *,
    snapshot_loader: Callable[[str, str | None], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    links = confirmed_repository_links()
    if snapshot_loader is None and not github_config.configured():
        return {"ok": False, "configured": False, "source": "github", "skipped": True, "repositories": []}
    results = [
        refresh_repository_link(
            link["project_id"],
            link["repository"],
            force=force,
            snapshot_loader=snapshot_loader,
        )
        for link in links
    ]
    active = [item for item in results if not item.get("skipped")]
    return {
        "ok": bool(active) and all(item.get("ok") for item in active),
        "configured": True,
        "source": "github",
        "skipped": not active,
        "repositories": results,
        "stale": any(item.get("stale") for item in results),
        "error": "; ".join(str(item["error"]) for item in results if item.get("error")) or None,
    }
