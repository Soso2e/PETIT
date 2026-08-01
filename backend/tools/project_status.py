"""Read-only project continuity status for conversational summaries."""
from __future__ import annotations

import json
from typing import Any

from .. import config, db, project_continuity
from .registry import tool


def _json_list(value: str | None) -> list[str]:
    try:
        decoded = json.loads(value or "[]")
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(decoded, list):
        return []
    return [str(item) for item in decoded if str(item).strip()]


@tool(
    name="get_project_status",
    description=(
        "PETIT内部に保存されたプロジェクトの現在状況を取得する。"
        "project_id省略時は未完了プロジェクトを現在選択中のものから順に返す。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "project_id": {"type": ["string", "null"]},
            "include_completed": {"type": "boolean", "default": False},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10},
        },
        "additionalProperties": False,
    },
)
def get_project_status(
    project_id: str | None = None,
    include_completed: bool = False,
    limit: int = 10,
) -> dict[str, Any]:
    project_continuity.ensure_project_schema()
    owner_id = config.PETIT_OWNER_ID
    target_id = str(project_id or "").strip() or None
    bounded_limit = max(1, min(int(limit), 20))

    where = ["p.status != 'archived'"]
    parameters: list[Any] = [owner_id, owner_id]
    if target_id:
        where.append("p.id = ?")
        parameters.append(target_id)
    elif not include_completed:
        where.append("COALESCE(c.stage, 'started') != 'completed'")
    parameters.append(bounded_limit)

    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT p.id, p.name, p.status, p.description, p.updated_at, "
            "c.stage, c.last_summary, c.next_action, c.blockers, c.completed_evidence, "
            "c.unverified_items, c.updated_at AS checkpoint_updated_at, "
            "CASE WHEN active.project_id = p.id THEN 1 ELSE 0 END AS is_current "
            "FROM projects p "
            "LEFT JOIN project_checkpoints c ON c.project_id=p.id AND c.user_id=? "
            "LEFT JOIN active_project_state active ON active.user_id=? AND active.project_id=p.id "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY is_current DESC, COALESCE(c.updated_at, p.updated_at) DESC, p.name ASC LIMIT ?",
            parameters,
        ).fetchall()

        projects: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            providers = conn.execute(
                "SELECT DISTINCT provider FROM project_source_links "
                "WHERE project_id=? AND status='active' AND confirmed_at IS NOT NULL ORDER BY provider",
                (item["id"],),
            ).fetchall()
            projects.append(
                {
                    "id": item["id"],
                    "name": item["name"],
                    "status": item["status"],
                    "stage": item.get("stage") or "started",
                    "description": item.get("description"),
                    "last_summary": item.get("last_summary"),
                    "next_action": item.get("next_action"),
                    "blockers": _json_list(item.get("blockers")),
                    "completed_evidence": _json_list(item.get("completed_evidence")),
                    "unverified_items": _json_list(item.get("unverified_items")),
                    "is_current": bool(item.get("is_current")),
                    "source_providers": [str(provider["provider"]) for provider in providers],
                    "updated_at": item.get("checkpoint_updated_at") or item.get("updated_at"),
                }
            )

    return {
        "scope": "PETITの保存済みプロジェクト状況",
        "count": len(projects),
        "include_completed": bool(include_completed),
        "projects": projects,
    }
