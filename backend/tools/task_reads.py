"""Status-aware read path for task lists.

This module is imported after the legacy task modules and intentionally
re-registers ``get_tasks``. Writes remain in ``tasks`` / ``tasks_phase2``;
only the read contract is tightened here so existing callers stay compatible.
"""
from __future__ import annotations

from typing import Any

from .. import config, db, task_sync_queue
from ..task_taxonomy import AREAS, resolve_area
from . import tasks as legacy_tasks
from .registry import tool

_CANCELLED_STATUS_ALIASES = (
    "chancel",  # Current Notion database value.
    "cancel",
    "canceled",
    "cancelled",
    "キャンセル",
    "取消",
    "取り消し",
)
_CANCELLED_STATUS_KEYS = frozenset(_CANCELLED_STATUS_ALIASES)

TASK_RESPONSE_GUIDANCE = (
    "タスク件数はtotal_countを条件一致の総数、returned_countを今回表示した件数として扱う。"
    "returned_countや互換用countだけを見て全件数と断定しない。"
    "has_more=trueなら一部取得と明記する。キャンセルは進行中・未完了に数えず、"
    "status_summary.cancelledとして分けて説明する。"
)


def _normalize_status(value: Any) -> str:
    return str(value or "").strip().casefold()


def _done_status() -> str:
    return _normalize_status(config.NOTION_DONE_STATUS)


def _terminal_statuses() -> tuple[str, ...]:
    values = [_done_status(), *_CANCELLED_STATUS_ALIASES]
    return tuple(dict.fromkeys(value for value in values if value))


def _where_clause(conditions: list[str]) -> str:
    return " WHERE " + " AND ".join(conditions) if conditions else ""


def _status_summary(rows: list[Any]) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    active = 0
    completed = 0
    cancelled = 0
    cancelled_statuses: list[str] = []
    done_status = _done_status()

    for row in rows:
        raw_status = str(row["status"] or "unknown")
        count = int(row["count"] or 0)
        by_status[raw_status] = count
        normalized = _normalize_status(raw_status)
        if normalized == done_status:
            completed += count
        elif normalized in _CANCELLED_STATUS_KEYS:
            cancelled += count
            cancelled_statuses.append(raw_status)
        else:
            active += count

    return {
        "active": active,
        "completed": completed,
        "cancelled": cancelled,
        "cancelled_statuses": sorted(cancelled_statuses, key=str.casefold),
        "by_status": by_status,
    }


@tool(
    name="get_tasks",
    description=(
        "タスク一覧を取得する。既定ではDoneとキャンセル状態（NotionのChancel等）を除いた"
        "アクティブタスクだけを返す。status=allで全状態、status指定でその状態だけを返す。"
        "total_countは条件一致総数、returned_countは今回の表示件数で、has_more=trueなら一部取得。"
        "returned_countだけを全件数と断定しない。キャンセルを進行中として扱わず、"
        "status_summaryで分けて説明する。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "description": "絞り込むステータス。省略でアクティブのみ、allで完了・キャンセルを含む全状態。",
            },
            "area": {
                "type": "string",
                "enum": list(AREAS),
                "description": "責任の発生源で絞り込む。個人/グループ/大学/仕事。",
            },
            "project_id": {
                "type": "string",
                "description": "確認済みPETIT内部プロジェクトIDで絞り込む。任意。",
            },
            "limit": {"type": "integer", "description": "今回表示する最大件数", "default": 20},
        },
    },
)
def get_tasks(
    status: str | None = None,
    area: str | None = None,
    project_id: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    sync = legacy_tasks._try_notion_sync()  # noqa: SLF001 - preserve the existing sync boundary
    task_sync_queue.ensure_task_sync_schema()
    normalized_area, _ = resolve_area(area)
    normalized_status = _normalize_status(status)
    active_only = not normalized_status

    scope_conditions: list[str] = []
    scope_params: list[Any] = []
    if normalized_area:
        scope_conditions.append("area = ?")
        scope_params.append(normalized_area)
    if project_id:
        scope_conditions.append("project_id = ?")
        scope_params.append(project_id)

    conditions = list(scope_conditions)
    params = list(scope_params)
    if normalized_status and normalized_status != "all":
        conditions.append("LOWER(TRIM(status)) = ?")
        params.append(normalized_status)
    elif active_only:
        terminal = _terminal_statuses()
        placeholders = ", ".join("?" for _ in terminal)
        conditions.append(f"LOWER(TRIM(status)) NOT IN ({placeholders})")
        params.extend(terminal)

    where = _where_clause(conditions)
    bounded_limit = max(1, min(int(limit), 100))
    with db.get_connection() as conn:
        total_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM tasks_cache" + where,
                params,
            ).fetchone()[0]
        )
        rows = conn.execute(
            "SELECT id, source, title, status, due_date, priority, category, area, reason, url, done_date, "
            "project_id, project_external_id FROM tasks_cache"
            + where
            + " ORDER BY (due_date IS NULL), due_date ASC, id ASC LIMIT ?",
            [*params, bounded_limit],
        ).fetchall()
        summary_rows = conn.execute(
            "SELECT status, COUNT(*) AS count FROM tasks_cache"
            + _where_clause(scope_conditions)
            + " GROUP BY status ORDER BY status",
            scope_params,
        ).fetchall()

    tasks = [dict(row) for row in rows]
    returned_count = len(tasks)
    return {
        # Backward compatibility: count remains the number included in this payload.
        "count": returned_count,
        "returned_count": returned_count,
        "total_count": total_count,
        "has_more": returned_count < total_count,
        "tasks": tasks,
        "status_summary": _status_summary(summary_rows),
        "filters": {
            "status": status,
            "area": normalized_area,
            "project_id": project_id,
            "active_only": active_only,
        },
        "excluded_statuses": list(_terminal_statuses()) if active_only else [],
        "response_guidance": TASK_RESPONSE_GUIDANCE,
        "sync": sync,
    }
