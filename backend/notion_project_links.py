"""Confirmation helpers for Notion project mapping candidates."""
from __future__ import annotations

import json
from typing import Any

from . import db, notion_project_sync, project_continuity, project_source_links


def _decode(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (json.JSONDecodeError, TypeError):
        return fallback


def list_candidates(status: str = "pending", limit: int = 20) -> list[dict[str, Any]]:
    notion_project_sync.ensure_notion_project_schema()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM notion_source_candidates WHERE status=? ORDER BY updated_at DESC LIMIT ?",
            (status, max(1, min(limit, 100))),
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        metadata = _decode(item.pop("metadata_json", "{}"), {})
        suggestions = _decode(item.pop("suggested_project_ids", "[]"), [])
        item["metadata"] = metadata if isinstance(metadata, dict) else {}
        item["suggested_project_ids"] = suggestions if isinstance(suggestions, list) else []
        result.append(item)
    return result


def get_candidate(candidate_id: int) -> dict[str, Any] | None:
    notion_project_sync.ensure_notion_project_schema()
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM notion_source_candidates WHERE id=?",
            (candidate_id,),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    item["metadata"] = _decode(item.pop("metadata_json", "{}"), {})
    item["suggested_project_ids"] = _decode(item.pop("suggested_project_ids", "[]"), [])
    return item


def _existing_source_link(provider: str, external_id: str) -> dict[str, Any] | None:
    project_continuity.ensure_project_schema()
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM project_source_links WHERE provider=? AND external_id=?",
            (provider, external_id),
        ).fetchone()
    return dict(row) if row else None


def _remap_notion_tasks() -> int:
    notion_project_sync.ensure_notion_project_schema()
    updated = 0
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT id, project_external_ids FROM tasks_cache WHERE source='notion'"
        ).fetchall()
        for row in rows:
            external_ids = _decode(str(row["project_external_ids"] or "[]"), [])
            if not isinstance(external_ids, list):
                external_ids = []
            resolved: set[str] = set()
            for external_id in external_ids:
                link = conn.execute(
                    "SELECT project_id FROM project_source_links WHERE provider='notion' AND external_id=? "
                    "AND status='active' AND confirmed_at IS NOT NULL",
                    (str(external_id),),
                ).fetchone()
                if link:
                    resolved.add(str(link["project_id"]))
            project_id = next(iter(resolved)) if len(resolved) == 1 else None
            conn.execute(
                "UPDATE tasks_cache SET project_id=?, updated_at=? WHERE id=?",
                (project_id, db.now_iso(), row["id"]),
            )
            updated += 1
    return updated


def link_candidate(candidate_id: int, project_id: str) -> dict[str, Any]:
    """Confirm one Notion source candidate and refresh dependent task mappings."""
    candidate = get_candidate(candidate_id)
    if not candidate:
        raise ValueError("Notion project candidate not found")
    if candidate.get("provider") != "notion" or candidate.get("source_type") != "project":
        raise ValueError("candidate is not a Notion project")
    project = project_continuity.get_project(project_id)
    if not project:
        raise ValueError("internal project not found")

    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    existing = _existing_source_link("notion", str(candidate["external_id"]))
    if existing:
        if existing["project_id"] != project_id and existing["status"] == "active":
            raise ValueError("Notion source is already linked to another active project")
        if existing["status"] == "removed":
            link = project_source_links.reassign_removed_source_link(
                int(existing["id"]),
                project_id,
                external_url=candidate.get("external_url"),
                metadata=metadata,
                confirmed=True,
            )
        else:
            link = project_continuity.confirm_project_source_link(int(existing["id"]))
    else:
        link = project_continuity.link_project_source(
            project_id,
            "notion",
            str(candidate["external_id"]),
            external_url=candidate.get("external_url"),
            metadata=metadata,
            confirmed=True,
        )

    now = db.now_iso()
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE notion_source_candidates SET project_id=?, status='linked', updated_at=? WHERE id=?",
            (project_id, now, candidate_id),
        )
        conn.execute(
            "UPDATE notion_projects_cache SET internal_project_id=?, synced_at=? WHERE external_id=?",
            (project_id, now, candidate["external_id"]),
        )
    remapped = _remap_notion_tasks()
    return {
        "linked": True,
        "candidate_id": candidate_id,
        "project": project,
        "source_link": link,
        "tasks_remapped": remapped,
    }


def ignore_candidate(candidate_id: int) -> dict[str, Any]:
    candidate = get_candidate(candidate_id)
    if not candidate:
        raise ValueError("Notion project candidate not found")
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE notion_source_candidates SET status='ignored', project_id=NULL, updated_at=? WHERE id=?",
            (db.now_iso(), candidate_id),
        )
    return {"ignored": True, "candidate_id": candidate_id, "title": candidate["title"]}
