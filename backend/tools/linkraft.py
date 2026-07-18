"""Read sync and confirmation tools for Linkraft owner projects."""
from __future__ import annotations

from .. import linkraft_project_links, linkraft_sync
from .registry import tool


@tool(
    name="sync_linkraft_projects",
    description="Linkraftからそそ本人が作成したプロジェクト一覧を同期し、確認済みプロジェクトの差分を取得する。",
    parameters={"type": "object", "properties": {}},
)
def sync_linkraft_projects():
    return linkraft_sync.sync_if_configured(force=True)


@tool(
    name="get_linkraft_project_candidates",
    description="Linkraft同期で見つかった未確認の本人所有プロジェクト候補を取得する。",
    parameters={
        "type": "object",
        "properties": {
            "status": {"type": "string", "default": "pending"},
            "limit": {"type": "integer", "default": 20},
        },
    },
)
def get_linkraft_project_candidates(status: str = "pending", limit: int = 20):
    candidates = linkraft_project_links.list_candidates(status=status, limit=limit)
    return {"count": len(candidates), "candidates": candidates}


@tool(
    name="link_linkraft_project_candidate",
    description="確認済みのLinkraft本人所有プロジェクト候補をPETIT内部プロジェクトへ紐付ける。",
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
def link_linkraft_project_candidate(candidate_id: int, project_id: str):
    return linkraft_project_links.link_candidate(candidate_id, project_id)


@tool(
    name="ignore_linkraft_project_candidate",
    description="確認済みのLinkraftプロジェクト候補を無視対象にする。",
    parameters={
        "type": "object",
        "properties": {"candidate_id": {"type": "integer"}},
        "required": ["candidate_id"],
        "additionalProperties": False,
    },
    requires_confirmation=True,
)
def ignore_linkraft_project_candidate(candidate_id: int):
    return linkraft_project_links.ignore_candidate(candidate_id)
