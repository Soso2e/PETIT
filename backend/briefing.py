"""Daily briefing generation for PETIT.

予定・タスク・直近エピソードを集めて、「今日まず何をするか」まで絞る。
LM Studio が使える場合は自然文に整え、落ちている場合は定型文で返す。
"""
from __future__ import annotations

import logging
from datetime import date as date_type
from datetime import datetime
from typing import Any

from . import calendar_sync, db
from .lmstudio_client import LMStudioError, chat_completion

log = logging.getLogger(__name__)

_SYSTEM = """あなたはユーザー専用アシスタント「PETIT」。
今日の予定・タスク・最近の流れを見て、朝のブリーフィングを短く作ってください。

ルール:
- 日本語で自然に。1〜4文。
- 情報を並べすぎず、「今やる1個」を必ず最後に入れる。
- 予定やタスクが無い場合は、無いことを軽く伝えて次の一手を提案する。
- 医療・生活改善スコアのような評価はしない。"""


def _recent_context(limit: int = 2) -> list[dict[str, Any]]:
    """Prefer the current episode store; retain legacy summaries as migration fallback."""
    episodes = db.recent_episodes(limit=limit)
    return episodes if episodes else db.recent_summaries(limit=limit)


def create_daily_briefing(target_date: str | None = None) -> dict[str, Any]:
    """Create a compact daily briefing for target_date (YYYY-MM-DD)."""
    day = target_date or date_type.today().isoformat()
    notion_sync = _sync_notion()
    calendar_sync_status = calendar_sync.sync_if_configured()
    events = _events_for(day)
    tasks = _open_tasks(day)
    recent_context = _recent_context(limit=2)
    next_action = _pick_next_action(events, tasks, recent_context)
    context = {
        "date": day,
        "events": events,
        "tasks": tasks,
        "recent_context": recent_context,
        # Compatibility for older callers; values now come from episodes first.
        "recent_summaries": recent_context,
        "next_action": next_action,
        "notion_sync": notion_sync,
        "calendar_sync": calendar_sync_status,
        "calendar_source_status": _calendar_source_status(events, calendar_sync_status),
    }

    try:
        message = chat_completion(
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": _format_context(context)},
            ],
            tools=None,
            temperature=0.6,
        )
        text = (message.get("content") or "").strip()
        if text:
            return {**context, "message": text, "kind": "llm"}
    except LMStudioError as exc:
        log.debug("daily briefing via LLM failed: %s", exc)

    return {**context, "message": _fallback_message(day, events, tasks, next_action), "kind": "template"}


def _events_for(day: str) -> list[dict[str, Any]]:
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT id, source, title, start_time, end_time, location "
            "FROM calendar_events_cache WHERE start_time LIKE ? ORDER BY start_time ASC",
            (f"{day}%",),
        ).fetchall()
    return [dict(r) for r in rows]


def _open_tasks(day: str, limit: int = 8) -> list[dict[str, Any]]:
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT id, source, title, status, due_date, priority FROM tasks_cache "
            "WHERE lower(status) NOT IN ('done', 'cancelled', 'chancel', '完了') "
            "AND (due_date IS NULL OR due_date <= ?) "
            "ORDER BY (due_date IS NULL), due_date ASC, "
            "CASE lower(priority) WHEN 'high' THEN 0 WHEN 'mid' THEN 1 WHEN 'medium' THEN 1 ELSE 2 END "
            "LIMIT ?",
            (day, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def _sync_notion() -> dict[str, Any] | None:
    """Refresh the read cache before building a briefing."""
    try:
        from .tools.notion import sync_if_configured

        return sync_if_configured()
    except Exception as exc:  # noqa: BLE001
        return {"synced": 0, "error": type(exc).__name__}


def _calendar_source_status(events: list[dict[str, Any]], sync_status: dict[str, Any]) -> str:
    if sync_status.get("configured"):
        if sync_status.get("errors") and not sync_status.get("synced"):
            return "sync_failed_or_empty"
        return "synced" if events else "synced_empty"
    return "cached" if events else "not_synced_or_empty"


def _pick_next_action(
    events: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    recent_context: list[dict[str, Any]],
) -> str:
    if tasks:
        return f"まず「{tasks[0]['title']}」から始める"
    if events:
        return f"次の予定「{events[0]['title']}」の準備をする"
    if recent_context:
        summary = str(recent_context[-1].get("summary", "")).strip()
        if summary:
            return f"昨日までの流れを見て、{summary[:40]}の続きから再開する"
    return "今日やることを1つだけ決める"


def _format_context(context: dict[str, Any]) -> str:
    lines = [f"日付: {context['date']}"]
    lines.append("予定:")
    for event in context["events"][:6]:
        time = _hm(event.get("start_time"))
        place = f" @ {event['location']}" if event.get("location") else ""
        lines.append(f"- {time} {event['title']}{place}")
    if not context["events"]:
        lines.append("- キャッシュ0件（Googleカレンダー未同期の可能性があるため『予定なし』とは断定しない）")

    lines.append("未完了タスク:")
    for task in context["tasks"][:8]:
        due = f" / due {task['due_date']}" if task.get("due_date") else ""
        priority = f" / {task['priority']}" if task.get("priority") else ""
        lines.append(f"- {task['title']}{due}{priority}")
    if not context["tasks"]:
        lines.append("- なし")

    lines.append("最近の流れ:")
    for item in context["recent_context"][-2:]:
        lines.append(f"- {item.get('summary', '')}")
    if not context["recent_context"]:
        lines.append("- なし")

    lines.append(f"今やる1個: {context['next_action']}")
    return "\n".join(lines)


def _fallback_message(
    day: str,
    events: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    next_action: str,
) -> str:
    event_text = f"予定は{len(events)}件" if events else "予定は今のところなし"
    task_text = f"未完了タスクは{len(tasks)}件" if tasks else "期限つきの未完了タスクはなし"
    action = next_action.removeprefix("まず")
    return f"おはよう。今日は{day}、{event_text}で、{task_text}。まず{action}のがよさそう。"


def _hm(value: str | None) -> str:
    if not value:
        return ""
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).strftime("%H:%M")
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).strftime("%H:%M")
        except ValueError:
            pass
    return value
