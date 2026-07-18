"""Confirmation helpers for Linkraft owner-project candidates."""
from __future__ import annotations

import json
from typing import Any

from . import db, linkraft_sync, project_continuity, project_source_links


def _decode(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (json.JSONDecodeError, TypeError):
        return fallback


def list_candidates(status: str = "pending", limit: int = 20) -> list[dict[str, Any]]:
    linkraft_sync.ensure_linkraft_schema()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM linkraft_source_candidates WHERE status=? ORDER BY updated_at DESC LIMIT ?",
            (status, max(1, min(limit, 100))),
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["metadata"] = _decode(item.pop("metadata_json", "{}"), {})
        item["suggested_project_ids"] = _decode(item.pop("suggested_project_ids", "[]"), [])
        result.append(item)
    return result


def get_candidate(candidate_id: int) -> dict[str, Any] | None:
    linkraft_sync.ensure_linkraft_schema()
    with db.get_connection() as conn:
        row = conn.execute("SELECT * FROM linkraft_source_candidates WHERE id=?", (candidate_id,)).fetchone()
    if not row:
        return None
    item = dict(row)
    item["metadata"] = _decode(item.pop("metadata_json", "{}"), {})
    item["suggested_project_ids"] = _decode(item.pop("suggested_project_ids", "[]"), [])
    return item


def _existing_link(external_id: str) -> dict[str, Any] | None:
    project_continuity.ensure_project_schema()
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM project_source_links WHERE provider='linkraft' AND external_id=?",
            (external_id,),
        ).fetchone()
    return dict(row) if row else None


def link_candidate(candidate_id: int, project_id: str) -> dict[str, Any]:
    candidate = get_candidate(candidate_id)
    if not candidate:
        raise ValueError("Linkraft project candidate not found")
    project = project_continuity.get_project(project_id)
    if not project:
        raise ValueError("internal project not found")

    external_id = str(candidate["external_id"])
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    existing = _existing_link(external_id)
    if existing:
        if existing["project_id"] != project_id and existing["status"] == "active":
            raise ValueError("Linkraft source is already linked to another active project")
        if existing["status"] == "removed":
            link = project_source_links.reassign_removed_source_link(
                int(existing["id"]),
                project_id,
                metadata=metadata,
                confirmed=True,
            )
        else:
            link = project_continuity.link_project_source(
                project_id,
                "linkraft",
                external_id,
                metadata=metadata,
                confirmed=True,
            )
    else:
        link = project_continuity.link_project_source(
            project_id,
            "linkraft",
            external_id,
            metadata=metadata,
            confirmed=True,
        )

    now = db.now_iso()
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE linkraft_source_candidates SET project_id=?, status='linked', updated_at=? WHERE id=?",
            (project_id, now, candidate_id),
        )
        conn.execute(
            "UPDATE linkraft_projects_cache SET internal_project_id=?, synced_at=? WHERE external_id=?",
            (project_id, now, external_id),
        )
    return {
        "linked": True,
        "candidate_id": candidate_id,
        "project": project,
        "source_link": link,
    }


def ignore_candidate(candidate_id: int) -> dict[str, Any]:
    candidate = get_candidate(candidate_id)
    if not candidate:
        raise ValueError("Linkraft project candidate not found")
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE linkraft_source_candidates SET status='ignored', project_id=NULL, updated_at=? WHERE id=?",
            (db.now_iso(), candidate_id),
        )
    return {"ignored": True, "candidate_id": candidate_id, "name": candidate["name"]}
