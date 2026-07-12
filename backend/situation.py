"""Read-only situational context collection for proactive assistant turns."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from . import calendar_sync, config, db

_PLANNING_WORDS = (
    "今日", "明日", "今週", "予定", "タスク", "やること", "何すれば", "優先", "期限",
    "締切", "進捗", "次に", "計画", "忙しい", "空いて", "朝", "おはよう",
)


def build_context_block(user_message: str) -> str:
    """Collect tasks and schedule only when the turn needs planning context."""
    compact = "".join(user_message.split())
    if not any(word in compact for word in _PLANNING_WORDS):
        return ""

    sync_status = _sync_notion_read_only()
    calendar_status = calendar_sync.sync_if_configured()
    today = date.today()
    horizon = (today + timedelta(days=7)).isoformat()
    with db.get_connection() as conn:
        tasks = [dict(row) for row in conn.execute(
            "SELECT title, status, due_date, priority, category FROM tasks_cache "
            "WHERE lower(status) NOT IN ('done', 'cancelled', 'chancel', '完了') "
            "ORDER BY (due_date IS NULL), due_date ASC, "
            "CASE lower(priority) WHEN 'high' THEN 0 WHEN 'mid' THEN 1 ELSE 2 END LIMIT 10"
        ).fetchall()]
        events = [dict(row) for row in conn.execute(
            "SELECT title, start_time, end_time, location, source FROM calendar_events_cache "
            "WHERE start_time >= ? AND start_time < ? ORDER BY start_time ASC LIMIT 10",
            (today.isoformat(), horizon),
        ).fetchall()]

    lines = [
        "【現在の状況データ】",
        "以下は読み取り専用で取得した状況。回答に必要な部分だけ使い、一覧をそのまま読み上げない。",
        f"- Notion同期: {sync_status}",
        f"- カレンダー同期: {_format_calendar_status(calendar_status)}",
        "- 未完了タスク:",
    ]
    lines.extend(
        f"    - {task['title']} / status={task['status']} / due={task.get('due_date') or 'なし'} / priority={task.get('priority') or 'なし'}"
        for task in tasks
    )
    if not tasks:
        lines.append("    - なし")
    lines.append("- 今後7日間の予定キャッシュ:")
    lines.extend(f"    - {event['start_time']} {event['title']} ({event['source']})" for event in events)
    if not events:
        if calendar_status.get("configured") and not calendar_status.get("errors"):
            lines.append("    - 0件。同期済みソース上では直近予定なし。")
        else:
            lines.append("    - 0件。GoogleカレンダーはPETIT本体へ未同期の可能性があるため、予定なしとは断定しない。")
    return "\n".join(lines)


def _sync_notion_read_only() -> str:
    if not config.notion_configured():
        return "未設定（ローカルキャッシュを使用）"
    try:
        from .tools.notion import sync_if_configured

        result: dict[str, Any] | None = sync_if_configured()
    except Exception as exc:  # noqa: BLE001
        return f"失敗（既存キャッシュを使用: {type(exc).__name__}）"
    if not result:
        return "未実行（既存キャッシュを使用）"
    if result.get("error"):
        return "失敗（既存キャッシュを使用）"
    return f"成功（{result.get('synced', 0)}件）"


def _format_calendar_status(result: dict[str, Any]) -> str:
    if not result.get("configured"):
        return "未設定（ローカル予定キャッシュを使用）"
    if result.get("errors") and not result.get("synced"):
        return "失敗（既存キャッシュを使用）"
    cached = " / TTL内" if result.get("cached") else ""
    return f"成功（{result.get('synced', 0)}件{cached}）"
