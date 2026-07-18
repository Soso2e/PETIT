"""BRAIN note discovery and confirmation-first project mapping tools."""
from __future__ import annotations

from .. import brain_project_sync
from .registry import tool


@tool(
    name="discover_brain_project_candidates",
    description="内部projectの正式名・別名でBRAIN Markdownを限定検索し、未確認ノート候補として保存する。",
    parameters={
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
            "limit": {"type": "integer", "default": 10},
        },
        "required": ["project_id"],
        "additionalProperties": False,
    },
)
def discover_brain_project_candidates(project_id: str, limit: int = 10):
    return brain_project_sync.discover_project_candidates(project_id, limit=limit)


@tool(
    name="inspect_brain_note_candidate",
    description="明示されたVault内相対Markdown pathをBRAIN project候補として安全に読み取る。自動linkはしない。",
    parameters={
        "type": "object",
        "properties": {
            "relative_path": {"type": "string"},
            "vault_index": {"type": "integer", "default": 0},
            "project_id": {"type": "string"},
        },
        "required": ["relative_path"],
        "additionalProperties": False,
    },
)
def inspect_brain_note_candidate(
    relative_path: str,
    vault_index: int = 0,
    project_id: str | None = None,
):
    return brain_project_sync.inspect_note(
        relative_path,
        vault_index=vault_index,
        project_id=project_id,
    )


@tool(
    name="get_brain_note_candidates",
    description="BRAINから見つけた未確認project note候補を取得する。",
    parameters={
        "type": "object",
        "properties": {
            "status": {"type": "string", "default": "pending"},
            "limit": {"type": "integer", "default": 20},
        },
    },
)
def get_brain_note_candidates(status: str = "pending", limit: int = 20):
    candidates = brain_project_sync.list_candidates(status=status, limit=limit)
    return {"count": len(candidates), "candidates": candidates}


@tool(
    name="link_brain_note_candidate",
    description="確認済みBRAINノート候補をPETIT内部projectへ紐付ける。Markdown本文は変更しない。",
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
def link_brain_note_candidate(candidate_id: int, project_id: str):
    return brain_project_sync.link_candidate(candidate_id, project_id)


@tool(
    name="ignore_brain_note_candidate",
    description="確認済みBRAINノート候補を無視対象にする。Markdown本文は変更しない。",
    parameters={
        "type": "object",
        "properties": {"candidate_id": {"type": "integer"}},
        "required": ["candidate_id"],
        "additionalProperties": False,
    },
    requires_confirmation=True,
)
def ignore_brain_note_candidate(candidate_id: int):
    return brain_project_sync.ignore_candidate(candidate_id)
