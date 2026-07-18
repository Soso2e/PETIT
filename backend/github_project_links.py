"""Confirmation-first mapping between GitHub repositories and PETIT projects."""
from __future__ import annotations

import json
from typing import Any

from . import db, github_sync, project_continuity


def _decode_candidate(row: Any) -> dict[str, Any]:
    item = dict(row)
    for key, fallback in (("metadata_json", {}), ("suggested_project_ids", [])):
        raw = item.pop(key)
        try:
            item[key.removesuffix("_json")] = json.loads(str(raw or ""))
        except json.JSONDecodeError:
            item[key.removesuffix("_json")] = fallback
    return item


def list_candidates(status: str = "pending", limit: int = 20) -> list[dict[str, Any]]:
    github_sync.ensure_github_schema()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM github_repository_candidates WHERE status=? ORDER BY updated_at DESC LIMIT ?",
            (status, max(1, min(limit, 100))),
        ).fetchall()
    return [_decode_candidate(row) for row in rows]


def get_candidate(candidate_id: int) -> dict[str, Any] | None:
    github_sync.ensure_github_schema()
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM github_repository_candidates WHERE id=?",
            (candidate_id,),
        ).fetchone()
    return _decode_candidate(row) if row else None


def link_candidate(candidate_id: int, project_id: str) -> dict[str, Any]:
    candidate = get_candidate(candidate_id)
    if not candidate:
        raise ValueError("GitHub repository candidate not found")
    if candidate["status"] == "ignored":
        raise ValueError("ignored GitHub repository candidate must be re-discovered before linking")
    if not project_continuity.get_project(project_id):
        raise ValueError("project not found")

    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    link = project_continuity.link_project_source(
        project_id,
        "github",
        str(candidate["full_name"]),
        external_url=candidate.get("html_url"),
        metadata=metadata,
        confirmed=True,
    )
    now = db.now_iso()
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE github_repository_candidates SET project_id=?, status='linked', updated_at=? WHERE id=?",
            (project_id, now, candidate_id),
        )
        conn.execute(
            "UPDATE github_repositories_cache SET internal_project_id=?, synced_at=? "
            "WHERE lower(full_name)=lower(?)",
            (project_id, now, candidate["full_name"]),
        )
        conn.execute(
            "UPDATE github_evidence_cache SET internal_project_id=? "
            "WHERE lower(repository_full_name)=lower(?)",
            (project_id, candidate["full_name"]),
        )
    return {"linked": True, "candidate": get_candidate(candidate_id), "source_link": link}


def ignore_candidate(candidate_id: int) -> dict[str, Any]:
    candidate = get_candidate(candidate_id)
    if not candidate:
        raise ValueError("GitHub repository candidate not found")
    now = db.now_iso()
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE github_repository_candidates SET status='ignored', project_id=NULL, updated_at=? WHERE id=?",
            (now, candidate_id),
        )
    return {"ignored": True, "candidate": get_candidate(candidate_id)}
