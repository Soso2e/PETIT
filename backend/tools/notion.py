"""Notion project/task synchronization with per-source freshness."""
from __future__ import annotations

from typing import Any

from .. import notion_project_sync, notion_task_sync
from .registry import tool


# Backward-compatible name for tests or callers that imported the old helper.
def _upsert_tasks(tasks: list[dict[str, Any]]) -> int:
    return notion_project_sync.upsert_tasks(tasks)


def status() -> dict[str, Any]:
    return notion_project_sync.status()


def sync_if_configured(force: bool = False) -> dict[str, Any]:
    return notion_project_sync.sync_all_if_configured(force=force)


@tool(
    name="sync_notion_tasks",
    description=(
        "NotionタスクDBを明示的にSQLiteへ同期する。通常のget_tasksはSQLiteから即答するため、"
        "『Notionの最新を確認して』『全件を照合して』のように最新性を明示された場合だけ使う。"
        "mode=incrementalは更新分、mode=fullは削除を含む全件整合性確認。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["incremental", "full"],
                "default": "incremental",
                "description": "通常はincremental。削除や全体不整合も確認する場合はfull。",
            }
        },
    },
)
def sync_notion_tasks(mode: str = "incremental") -> dict[str, Any]:
    return notion_task_sync.sync_now(mode=mode)
