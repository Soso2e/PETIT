"""Confirmation-gated chat tool for Life-first task hierarchy."""
from __future__ import annotations

from typing import Any

from .. import task_hierarchy
from .registry import tool


@tool(
    name="set_task_parent",
    description=(
        "既存タスクを別のタスクの子にする、またはLife直下へ戻す。"
        "『XをPETIT開発の子タスクにして』『XをLife直下へ戻して』のような依頼で使う。"
        "親として選べるのはLife直下のタスクだけ。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "task_id": {"type": "integer"},
            "external_id": {"type": "string"},
            "title_query": {"type": "string"},
            "parent_task_id": {"type": "integer"},
            "parent_title_query": {"type": "string"},
            "move_to_life": {"type": "boolean", "default": False},
        },
    },
    requires_confirmation=True,
)
def set_task_parent_tool(
    task_id: int | str | None = None,
    external_id: str | None = None,
    title_query: str | None = None,
    parent_task_id: int | str | None = None,
    parent_title_query: str | None = None,
    move_to_life: bool = False,
) -> dict[str, Any]:
    return task_hierarchy.set_task_parent(
        task_id=task_id,
        external_id=external_id,
        title_query=title_query,
        parent_task_id=parent_task_id,
        parent_title_query=parent_title_query,
        move_to_life=move_to_life,
    )
