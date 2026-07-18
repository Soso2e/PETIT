"""Safe lifecycle helpers for project-to-external-source links.

The base repository keeps removed links as tombstones so the same external id
cannot silently move between projects. This module provides the explicit,
confirmed reassignment path required when the user changes that mapping later.
"""
from __future__ import annotations

import json
from typing import Any

from . import db, project_continuity


def reassign_removed_source_link(
    link_id: int,
    new_project_id: str,
    *,
    external_url: str | None = None,
    metadata: dict[str, Any] | None = None,
    confirmed: bool = False,
) -> dict[str, Any]:
    """Move an explicitly removed source link to another project.

    Active links cannot be moved. Call `remove_project_source_link()` first so
    accidental or concurrent reassignment never changes a live mapping.
    """
    project_continuity.ensure_project_schema()
    now = db.now_iso()
    with db.get_connection() as conn:
        project = conn.execute(
            "SELECT 1 FROM projects WHERE id=?",
            (new_project_id,),
        ).fetchone()
        if not project:
            raise ValueError("project not found")
        link = conn.execute(
            "SELECT * FROM project_source_links WHERE id=?",
            (link_id,),
        ).fetchone()
        if not link:
            raise ValueError("source link not found")
        if link["status"] != "removed":
            raise ValueError("active source link must be removed before reassignment")
        metadata_json = (
            json.dumps(metadata, ensure_ascii=False, sort_keys=True)
            if metadata is not None
            else str(link["metadata_json"] or "{}")
        )
        next_url = external_url if external_url is not None else link["external_url"]
        confirmed_at = now if confirmed else None
        conn.execute(
            "UPDATE project_source_links SET project_id=?, external_url=?, metadata_json=?, "
            "status='active', confirmed_at=?, updated_at=? WHERE id=?",
            (new_project_id, next_url, metadata_json, confirmed_at, now, link_id),
        )
    return project_continuity.get_project_source_link(link_id) or {}


def source_link_history(provider: str, external_id: str) -> dict[str, Any] | None:
    """Return the current mapping/tombstone for audit and confirmation screens."""
    project_continuity.ensure_project_schema()
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT l.*, p.name AS project_name FROM project_source_links l "
            "JOIN projects p ON p.id=l.project_id "
            "WHERE l.provider=? AND l.external_id=?",
            (provider.strip().casefold(), external_id.strip()),
        ).fetchone()
    return dict(row) if row else None
