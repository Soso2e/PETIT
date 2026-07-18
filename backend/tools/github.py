"""Read-only GitHub evidence and confirmation tools."""
from __future__ import annotations

from .. import github_project_links, github_sync
from .registry import tool


@tool(
    name="inspect_github_repository",
    description="owner/nameで指定したGitHub repositoryを読み取り、PETIT projectへの未確認候補として保存する。",
    parameters={
        "type": "object",
        "properties": {
            "repository": {
                "type": "string",
                "description": "GitHub repository。owner/name形式またはgithub.com URL。",
            }
        },
        "required": ["repository"],
        "additionalProperties": False,
    },
)
def inspect_github_repository(repository: str):
    return github_sync.inspect_repository(repository)


@tool(
    name="sync_github_evidence",
    description="確認済みGitHub repositoryのcommit・PR・check・deploymentを読み取り同期する。checkpointは変更しない。",
    parameters={"type": "object", "properties": {}},
)
def sync_github_evidence():
    return github_sync.sync_if_configured(force=True)


@tool(
    name="get_github_repository_candidates",
    description="GitHubから読み取った未確認repository候補を取得する。自動紐付けは行わない。",
    parameters={
        "type": "object",
        "properties": {
            "status": {"type": "string", "default": "pending"},
            "limit": {"type": "integer", "default": 20},
        },
    },
)
def get_github_repository_candidates(status: str = "pending", limit: int = 20):
    candidates = github_project_links.list_candidates(status=status, limit=limit)
    return {"count": len(candidates), "candidates": candidates}


@tool(
    name="link_github_repository_candidate",
    description="確認済みGitHub repository候補をPETIT内部projectへ紐付ける。",
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
def link_github_repository_candidate(candidate_id: int, project_id: str):
    return github_project_links.link_candidate(candidate_id, project_id)


@tool(
    name="ignore_github_repository_candidate",
    description="確認済みGitHub repository候補を無視対象にする。",
    parameters={
        "type": "object",
        "properties": {"candidate_id": {"type": "integer"}},
        "required": ["candidate_id"],
        "additionalProperties": False,
    },
    requires_confirmation=True,
)
def ignore_github_repository_candidate(candidate_id: int):
    return github_project_links.ignore_candidate(candidate_id)
