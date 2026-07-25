"""Status-aware local read path for task lists.

This module is imported after the legacy task modules and intentionally
re-registers ``get_tasks``. Writes remain in ``tasks`` / ``tasks_phase2``;
reads never wait for Notion and expose live-sync freshness separately.
"""
from __future__ import annotations

from typing import Any

from .. import config, db, notion_task_sync, task_sync_queue
from ..task_taxonomy import AREAS, resolve_area
from . import tasks as legacy_tasks  # Backward-compatible test/caller surface; no implicit sync call.
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
_PRIORITY_FILTERS = {
    "high": ("high",),
    "mid": ("mid", "medium"),
    "medium": ("mid", "medium"),
    "low": ("low",),
    "later": ("mid", "medium", "low"),
    "all": (),
}

TASK_RESPONSE_GUIDANCE = (
    "タスク件数はtotal_countを条件一致の総数、returned_countを今回表示した件数として扱う。"
    "returned_countや互換用countだけを見て全件数と断定しない。"
    "has_more=trueなら一部取得と明記する。"
    "通常のタスク確認はpriority=high（省略時に自動適用）でHighだけを返す。"
    "暇・やりたいこと・後回し候補はpriority=laterでMid/MediumとLowを返し、"
    "全部のタスクを求められた時だけpriority=allを使う。"
    "タスクはHigh、Mid、Low、未設定の順で返る。"
    "キャンセルは進行中・未完了に数えず、status_summary.cancelledとして分けて説明する。"
    "通常はSQLiteの統合ビューを即答に使い、sync.tasks.pending_writes/failed_writes/conflictsがある時だけ"
    "未同期・競合を明示する。明示的に最新確認を求められた場合だけsync_notion_tasksを使う。"
)


def _normalize_status(value: Any) -> str:
    return str(value or "").strip().casefold()


def _done_status() -> str:
    return _normalize_status(config.NOTION_DONE_STATUS)


def _terminal_statuses() -> tuple[str, ...]:
    values = [_done_status(), *_CANCELLED_STATUS_ALIASES]
    return tuple(dict.fromkeys(value for value in values if value))


def _normalize_priority(value: Any) -> tuple[str, tuple[str, ...]]:
    normalized = str(value or "").strip().casefold() or "high"
    if normalized not in _PRIORITY_FILTERS:
        allowed = ", ".join(_PRIORITY_FILTERS)
        raise ValueError(f"priority must be one of: {allowed}")
    return normalized, _PRIORITY_FILTERS[normalized]


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
        "SQLiteの統合タスク一覧を即時取得する。通常会話ではNotion APIを待たない。"
        "既定ではPriority=Highかつ、Done、キャンセル、Notionで削除済みを除いたアクティブタスクだけを返す。"
        "日常的な『タスクは？』『何に追われてる？』ではpriorityを省略する。"
        "『暇』『やりたいこと』『後回し候補』ではpriority=later、"
        "『全部』『すべてのタスク』ではpriority=allを指定する。"
        "priority=mid/medium/lowで個別優先度も指定できる。"
        "status=allで全状態、status指定でその状態だけを返す。取得上限前にHigh、Mid、Low、未設定の順。"
        "total_countは条件一致総数、returned_countは今回返した件数、has_more=trueは一部取得を示す。"
        "returned_countだけを全件数と断定しない。キャンセルを進行中として扱わず、"
        "status_summary.cancelledとして分離する。同期鮮度、未送信、失敗、競合はsyncで確認する。"
        "明示的な最新確認だけsync_notion_tasksを使う。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "description": "絞り込むステータス。省略でアクティブのみ、allで完了・キャンセルを含む全状態。",
            },
            "priority": {
                "type": "string",
                "enum": ["high", "mid", "medium", "low", "later", "all"],
                "description": (
                    "優先度範囲。省略/highはHighのみ。laterはMid/MediumとLow。"
                    "allは未設定を含む全優先度。全部を求められた場合だけallを使う。"
                ),
                "default": "high",
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
    priority: str | None = None,
) -> dict[str, Any]:
    task_sync_queue.ensure_task_sync_schema()
    notion_task_sync.ensure_schema()
    normalized_area, _ = resolve_area(area)
    normalized_status = _normalize_status(status)
    normalized_priority, priority_values = _normalize_priority(priority)
    active_only = not normalized_status

    scope_conditions: list[str] = ["COALESCE(remote_deleted_at, '') = ''"]
    scope_params: list[Any] = []
    if normalized_area:
        scope_conditions.append("area = ?")
        scope_params.append(normalized_area)
    if project_id:
        scope_conditions.append("project_id = ?")
        scope_params.append(project_id)

    priority_conditions = list(scope_conditions)
    priority_params = list(scope_params)
    if priority_values:
        placeholders = ", ".join("?" for _ in priority_values)
        priority_conditions.append(
            f"LOWER(TRIM(COALESCE(priority, ''))) IN ({placeholders})"
        )
        priority_params.extend(priority_values)

    conditions = list(priority_conditions)
    params = list(priority_params)
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
            "project_id, project_external_id, sync_status, sync_error, source_updated_at, last_synced_at "
            "FROM tasks_cache"
            + where
            + " ORDER BY CASE LOWER(TRIM(COALESCE(priority, ''))) "
            "WHEN 'high' THEN 0 WHEN 'mid' THEN 1 WHEN 'medium' THEN 1 "
            "WHEN 'low' THEN 2 ELSE 3 END, "
            "(due_date IS NULL), due_date ASC, id ASC LIMIT ?",
            [*params, bounded_limit],
        ).fetchall()
        summary_rows = conn.execute(
            "SELECT status, COUNT(*) AS count FROM tasks_cache"
            + _where_clause(priority_conditions)
            + " GROUP BY status ORDER BY status",
            priority_params,
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
            "priority": normalized_priority,
            "priority_defaulted": not str(priority or "").strip(),
            "area": normalized_area,
            "project_id": project_id,
            "active_only": active_only,
            "remote_deleted_excluded": True,
        },
        "excluded_statuses": list(_terminal_statuses()) if active_only else [],
        "response_guidance": TASK_RESPONSE_GUIDANCE,
        "sync": notion_task_sync.status(),
    }
