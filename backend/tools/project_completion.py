"""Approved write tool for project completion checkpoints and events."""
from __future__ import annotations

from .. import project_completion
from .registry import tool


@tool(
    name="save_project_completion",
    description="確認済みのプロジェクト終了状態をcheckpointとPETITイベントへ保存する。",
    parameters={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "project_id": {"type": "string"},
            "stage": {"type": "string"},
            "last_summary": {"type": "string"},
            "next_action": {"type": ["string", "null"]},
            "blockers": {"type": "array", "items": {"type": "string"}},
            "completed_evidence": {"type": "array", "items": {"type": "string"}},
            "unverified_items": {"type": "array", "items": {"type": "string"}},
            "event_type": {"type": "string"},
            "event_summary": {"type": "string"},
            "source_user_text": {"type": "string"},
            "idempotency_key": {"type": "string"},
        },
        "required": [
            "user_id",
            "project_id",
            "stage",
            "last_summary",
            "event_type",
            "event_summary",
            "source_user_text",
            "idempotency_key",
        ],
        "additionalProperties": False,
    },
    requires_confirmation=True,
)
def save_project_completion(**kwargs):
    return project_completion.commit_completion(**kwargs)
