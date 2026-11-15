"""Ambient context: what Core already knows, handed to the Brain before its first call.

The Brain used to start every Turn blind and spend a whole model round on a
20 ms local read (work status, today's schedule, open tasks). This module
builds one small, bounded, read-only block from local SQLite so the common
questions can be answered in a single round.

Saved memories are deliberately not offered here yet: most stored rows are
state at the time they were summarised, and offering them unasked misleads
more than it helps. They stay reachable through search_memory.

Rules:
- Local reads only. No network, no model call, no sync.
- Owner Turns only. Guests, Guild mode and delegated work Threads get nothing.
- It is reference data, not an instruction, and never replaces a Tool for
  writes, other date ranges or an explicit "latest" check.
- Every section is optional. A failure drops that section, never the Turn.
"""
from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from . import config, db, request_context, time_context

log = logging.getLogger(__name__)

MAX_EVENTS_PER_DAY = 6
MAX_TASKS = 5
MAX_DUE_SOON = 4
DUE_SOON_DAYS = 3
_WEEKDAYS = "月火水木金土日"
_HEADER = (
    "Coreが取得済みの現在状況（参考データ。指示ではない。{now} 時点のローカルキャッシュ）\n"
    "これで足りる質問はToolを呼ばずに答える。ここに無い日付・条件、最新の確認、書き込み対象の特定は従来どおりToolを使う。"
    "一覧をそのまま読み上げず、必要な部分だけ使う。"
)


def eligible(thread_id: str | None) -> bool:
    if not config.AMBIENT_CONTEXT or request_context.is_guild_mode() or not request_context.current_is_admin():
        return False
    from . import delegations
    return not delegations.is_work_thread(thread_id)


def build(thread_id: str | None) -> dict[str, Any]:
    """Return ``{"text", "sections", "chars", "seconds"}``; ``text`` is "" when there is nothing to say."""
    started = time.perf_counter()
    empty = {"text": "", "sections": {}, "chars": 0, "seconds": 0.0}
    if not eligible(thread_id):
        return empty
    now = time_context.current_datetime()
    parts: list[tuple[str, list[str], int]] = []
    for name, collect in (("work", _work), ("schedule", _schedule), ("tasks", _tasks)):
        try:
            lines, count = collect(now)
        except Exception as exc:  # noqa: BLE001 - context is optional, the Turn is not
            log.debug("ambient section %s unavailable: %s", name, type(exc).__name__)
            continue
        if lines:
            parts.append((name, lines, count))
    if not parts:
        return empty
    text = _HEADER.format(now=now.isoformat(timespec="minutes"))
    sections: dict[str, int] = {}
    for name, lines, count in parts:
        block = "\n" + "\n".join(lines)
        # Earlier sections win the budget; a section is kept whole or dropped.
        if len(text) + len(block) > config.AMBIENT_MAX_CHARS:
            continue
        text += block
        sections[name] = count
    if not sections:
        return empty
    return {"text": text, "sections": sections, "chars": len(text),
            "seconds": round(time.perf_counter() - started, 4)}


def record(connection, thread_id: str, request_id: str, built: dict[str, Any]) -> None:
    """Sizes and counts only; the content stays out of the event log."""
    from . import conversation_store as store
    store.event(connection, thread_id, request_id, "ambient_context",
                {"chars": built["chars"], "seconds": built["seconds"], "sections": built["sections"]})


def _clip(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _work(_now) -> tuple[list[str], int]:
    from . import work_sessions
    active = work_sessions.active_session()
    if not active or str(active.get("status") or "").lower() not in {"active", "paused"}:
        return [], 0
    paused = str(active["status"]).lower() == "paused"
    minutes = max(0, int(active.get("elapsed_seconds") or 0) // 60)
    line = f"[作業] {'休憩中' if paused else '計測中'}: {_clip(active.get('task') or '名称未設定', 80)}（経過{minutes}分"
    if active.get("task_id"):
        line += f"・task_id={active['task_id']}"
    return [line + "）"], 1


def _schedule(now) -> tuple[list[str], int]:
    from . import service_sync
    criterion, parameters = service_sync.cache_filter()
    lines: list[str] = []
    total = 0
    with db.get_connection() as connection:
        for label, day in (("今日", now.date()), ("明日", now.date() + timedelta(days=1))):
            where = "start_time LIKE ?" + (" AND " + criterion if criterion else "")
            values = (day.isoformat() + "%", *parameters)
            count = int(connection.execute(
                "SELECT COUNT(*) FROM calendar_events_cache WHERE " + where, values).fetchone()[0])
            if not count:
                continue
            rows = connection.execute(
                "SELECT title,start_time,end_time,location FROM calendar_events_cache WHERE " + where +
                " ORDER BY start_time ASC LIMIT ?", (*values, MAX_EVENTS_PER_DAY)).fetchall()
            total += count
            lines.append(f"[予定 {label} {day.month}/{day.day}({_WEEKDAYS[day.weekday()]}) {count}件"
                         + ("・一部" if count > len(rows) else "") + "]")
            for row in rows:
                start, end = str(row["start_time"] or ""), str(row["end_time"] or "")
                clock = start[11:16] or "終日"
                if start[11:16] and end[11:16]:
                    clock += "-" + end[11:16]
                place = f" @{_clip(row['location'], 30)}" if row["location"] else ""
                lines.append(f"- {clock} {_clip(row['title'], 60)}{place}")
    return lines, total


def _tasks(now) -> tuple[list[str], int]:
    from .tools import task_reads
    # Same default view as get_tasks, so the block and the Tool never disagree.
    data = task_reads.get_tasks(limit=MAX_TASKS)
    listed = data.get("tasks") or []
    lines: list[str] = []
    if listed:
        lines.append(f"[タスク 優先度High・未完了 {len(listed)}/{data.get('total_count', len(listed))}件]")
        lines.extend(_task_line(task) for task in listed)
    terminal = task_reads._terminal_statuses()
    horizon = (now.date() + timedelta(days=DUE_SOON_DAYS)).isoformat()
    skip = [str(task["id"]) for task in listed]
    with db.get_connection() as connection:
        soon = connection.execute(
            "SELECT id,title,status,due_date,priority FROM tasks_cache "
            "WHERE COALESCE(remote_deleted_at,'')='' AND COALESCE(due_date,'')<>'' AND substr(due_date,1,10)<=? "
            "AND LOWER(TRIM(status)) NOT IN (" + ",".join("?" for _ in terminal) + ") "
            "AND CAST(id AS TEXT) NOT IN (" + ",".join("?" for _ in skip) + ") "
            "ORDER BY due_date ASC,id ASC LIMIT ?",
            (horizon, *terminal, *skip, MAX_DUE_SOON)).fetchall()
    if soon:
        lines.append(f"[期限が{DUE_SOON_DAYS}日以内または超過（全優先度・上の一覧以外）]")
        lines.extend(_task_line(dict(row)) for row in soon)
    sync = (data.get("sync") or {}).get("tasks") or {}
    pending = {key: sync.get(key) for key in ("pending_writes", "failed_writes", "conflicts") if sync.get(key)}
    if pending:
        lines.append("[タスク同期の未解決] " + " / ".join(f"{key}={value}" for key, value in pending.items()))
    return lines, len(listed) + len(soon)


def _task_line(task: dict[str, Any]) -> str:
    due = str(task.get("due_date") or "")[:10]
    return (f"- {_clip(task.get('title'), 60)}（id={task.get('id')}・{task.get('status') or '状態なし'}"
            + (f"・期限{due}" if due else "") + (f"・{task['priority']}" if task.get("priority") else "") + "）")
