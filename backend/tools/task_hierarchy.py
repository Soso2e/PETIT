"""Confirmation-gated chat tool for Life-first task hierarchy."""
from __future__ import annotations

from typing import Any

from .. import task_hierarchy
from . import tasks_phase2
from .registry import tool


def _failed(result: dict[str, Any]) -> bool:
    return bool(result.get("error")) or result.get("updated") is False


@tool(
    name="set_task_parent",
    description=(
        "既存タスクを別のタスクの子にする、またはLife直下へ戻す。"
        "『XをPETIT開発の子タスクにして』『XをLife直下へ戻して』のような親子関係の依頼では、"
        "update_taskではなく必ずこのToolを使う。親として選べるのはLife直下のタスクだけ。"
        "同時にタスク名も変える場合はtitleを渡す。"
        "ユーザーへ自然文で事前確認を求めず、明示依頼を受けたらこのToolをcallする。"
        "確認はRuntimeが一度だけ表示する。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "task_id": {"type": "integer"},
            "id": {"type": "integer", "description": "task_idの互換別名。"},
            "external_id": {"type": "string"},
            "title_query": {"type": "string"},
            "title": {"type": "string", "description": "親子変更と同時に変更するタスク名。"},
            "parent_task_id": {"type": "integer"},
            "parent_id": {"type": "integer", "description": "parent_task_idの互換別名。"},
            "parent_title_query": {"type": "string"},
            "move_to_life": {"type": "boolean", "default": False},
        },
    },
    requires_confirmation=True,
)
def set_task_parent_tool(
    task_id: int | str | None = None,
    id: int | str | None = None,
    external_id: str | None = None,
    title_query: str | None = None,
    title: str | None = None,
    parent_task_id: int | str | None = None,
    parent_id: int | str | None = None,
    parent_title_query: str | None = None,
    move_to_life: bool = False,
) -> dict[str, Any]:
    resolved_task_id = task_id if task_id is not None else id
    resolved_parent_id = parent_task_id if parent_task_id is not None else parent_id

    normalized_title: str | None = None
    if title is not None:
        normalized_title = str(title).strip()
        if not normalized_title:
            return {"updated": False, "error": "タスク名を空にはできません。"}

    child = task_hierarchy._find_task(resolved_task_id, external_id, title_query)
    if child is None:
        return {"updated": False, "error": "対象タスクを1件に絞れませんでした。"}

    if not move_to_life:
        parent = task_hierarchy._resolve_parent(resolved_parent_id, parent_title_query)
        if parent is None:
            return {"updated": False, "error": "親タスクを1件に絞れませんでした。"}
        error = task_hierarchy._validate_parent(child, parent)
        if error:
            return {"updated": False, "error": error}

    title_result: dict[str, Any] | None = None
    if normalized_title is not None and normalized_title != str(child.get("title") or ""):
        title_result = tasks_phase2.update_task(
            task_id=int(child["id"]),
            title=normalized_title,
        )
        if _failed(title_result):
            return title_result

    parent_result = task_hierarchy.set_task_parent(
        task_id=int(child["id"]),
        parent_task_id=resolved_parent_id,
        parent_title_query=parent_title_query,
        move_to_life=move_to_life,
    )
    if _failed(parent_result):
        if title_result and title_result.get("updated"):
            return {
                **parent_result,
                "partial_update": True,
                "title_updated": True,
                "message": "タスク名は変更しましたが、親子関係の変更に失敗しました。",
            }
        return parent_result

    if title_result:
        parent_result = {
            **parent_result,
            "title_updated": True,
            "title": normalized_title,
        }
    return parent_result
