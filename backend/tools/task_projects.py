"""Confirmation-first task-to-project classification for chat."""
from __future__ import annotations

from typing import Any

from .. import project_continuity
from . import tasks_phase2
from .registry import tool


def _project_candidate(project_name: str | None, project_id: str | None) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    project_continuity.ensure_project_schema()
    if project_id:
        project = project_continuity.get_project(str(project_id))
        return project, [] if project else []

    name = str(project_name or "").strip()
    if not name:
        return None, []
    candidates = project_continuity.find_projects_by_alias(name)
    if len(candidates) == 1:
        return candidates[0], []
    return None, candidates


@tool(
    name="classify_task_project",
    description=(
        "既存Taskを既存Projectへ分類・移動する。"
        "『未分類のXをPETIT開発へ移して』『XをRoomiesのTaskにして』のような依頼で使う。"
        "Project名は登録済みaliasから厳密に解決し、Notion Taskは確認済みRelationだけを更新する。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "task_id": {"type": "integer", "description": "PETITのローカルTask ID。分かる場合に指定する。"},
            "external_id": {"type": "string", "description": "NotionページID。分かる場合に指定する。"},
            "title_query": {"type": "string", "description": "Task名の一部。task_idが不明な場合に指定する。"},
            "project_id": {"type": "string", "description": "PETIT内部Project ID。分かる場合に指定する。"},
            "project_name": {"type": "string", "description": "登録済みProject名またはalias。"},
        },
        "anyOf": [
            {"required": ["task_id"]},
            {"required": ["external_id"]},
            {"required": ["title_query"]},
        ],
    },
    requires_confirmation=True,
)
def classify_task_project(
    task_id: int | str | None = None,
    external_id: str | None = None,
    title_query: str | None = None,
    project_id: str | None = None,
    project_name: str | None = None,
) -> dict[str, Any]:
    project, candidates = _project_candidate(project_name, project_id)
    if project is None:
        if candidates:
            return {
                "updated": False,
                "error": "Projectを1件に絞れませんでした。Project名をもう少し具体的にしてください。",
                "project_candidates": [
                    {"id": item.get("id"), "name": item.get("name"), "matched_alias": item.get("matched_alias")}
                    for item in candidates[:5]
                ],
            }
        return {
            "updated": False,
            "error": "指定された登録済みProjectが見つかりません。",
            "project_name": project_name,
            "project_id": project_id,
        }

    result = tasks_phase2.update_task(
        task_id=task_id,
        external_id=external_id,
        title_query=title_query,
        project_id=str(project["id"]),
    )
    if result.get("updated"):
        result["project"] = {"id": project["id"], "name": project["name"]}
        result["message"] = f"Taskを「{project['name']}」へ分類しました。"
    return result
