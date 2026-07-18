"""Tools for reviewing and confirming Notion project mapping candidates."""
from __future__ import annotations

from .. import notion_project_links
from .registry import tool


@tool(
    name="get_notion_project_candidates",
    description="Notion同期で見つかった未確認プロジェクト候補を取得する。自動紐付けは行わない。",
    parameters={
        "type": "object",
        "properties": {
            "status": {"type": "string", "default": "pending"},
            "limit": {"type": "integer", "default": 20},
        },
    },
)
def get_notion_project_candidates(status: str = "pending", limit: int = 20):
    candidates = notion_project_links.list_candidates(status=status, limit=limit)
    return {"count": len(candidates), "candidates": candidates}


@tool(
    name="link_notion_project_candidate",
    description="確認済みのNotionプロジェクト候補を指定したPETIT内部プロジェクトへ紐付ける。",
    parameters={
        "type": "object",
        "properties": {
            "candidate_id": {"type": "integer"},
            "project_id": {"type": "string"},
        },
        "required": ["candidate_id", "project_id"],
        "additionalProperties": False,
    },
    requires_confirmation=True,
)
def link_notion_project_candidate(candidate_id: int, project_id: str):
    return notion_project_links.link_candidate(candidate_id, project_id)


@tool(
    name="ignore_notion_project_candidate",
    description="確認済みのNotionプロジェクト候補を無視対象にする。",
    parameters={
        "type": "object",
        "properties": {"candidate_id": {"type": "integer"}},
        "required": ["candidate_id"],
        "additionalProperties": False,
    },
    requires_confirmation=True,
)
def ignore_notion_project_candidate(candidate_id: int):
    return notion_project_links.ignore_candidate(candidate_id)
