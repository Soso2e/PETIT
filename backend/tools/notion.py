"""Notion project/task synchronization with per-source freshness."""
from __future__ import annotations

from typing import Any

from .. import notion_project_sync
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
        "Notionの個人プロジェクトDBとタスクDBを読み取り同期し、Relation・担当者・親子タスクと"
        "ソース別fresh/stale状態を更新する。未確認プロジェクトは自動紐付けしない。"
    ),
    parameters={"type": "object", "properties": {}},
)
def sync_notion_tasks() -> dict[str, Any]:
    return sync_if_configured(force=True)
