"""Task write defaults layered on top of the Phase 2 implementation."""
from __future__ import annotations

from typing import Any

from ..task_taxonomy import AREAS
from . import tasks_phase2
from .registry import tool

_CATEGORIES = list(tasks_phase2._CATEGORIES)  # noqa: SLF001 - keep the registered contract aligned
_PRIORITIES = list(tasks_phase2._PRIORITIES)  # noqa: SLF001 - keep the registered contract aligned


@tool(
    name="create_task",
    description=(
        "新しいタスクを作成する。Notion設定時は承認後すぐSQLiteへ保存し、Notion書き込みは"
        "pendingキューでバックグラウンド実行する。priority省略時はHigh。"
        "due_dateはユーザーが日付を指定した場合だけ設定し、省略時は期限なしにする。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "due_date": {
                "type": "string",
                "description": "期限。ユーザーが日付を明示した場合だけ指定する。",
            },
            "priority": {
                "type": "string",
                "enum": _PRIORITIES,
                "description": "優先度。省略時はHigh。",
            },
            "area": {"type": "string", "enum": list(AREAS)},
            "project_id": {"type": "string"},
            "category": {
                "type": "string",
                "enum": _CATEGORIES,
                "description": "省略時はタイトル等から自動選別する。",
            },
            "reason": {"type": "string"},
        },
        "required": ["title"],
    },
    requires_confirmation=True,
)
def create_task(
    title: str,
    due_date: str | None = None,
    priority: str | None = None,
    area: str | None = None,
    project_id: str | None = None,
    category: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    normalized_priority = (
        tasks_phase2.legacy_tasks._normalize_option(priority, _PRIORITIES)  # noqa: SLF001
        or "High"
    )
    return tasks_phase2.create_task(
        title=title,
        due_date=due_date,
        priority=normalized_priority,
        area=area,
        project_id=project_id,
        category=category,
        reason=reason,
    )
