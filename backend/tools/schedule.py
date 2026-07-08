"""Schedule tools.

MVP reads a local SQLite calendar cache. Real calendar sources (Google /
Apple Calendar) can populate calendar_events_cache later.
"""
from __future__ import annotations

from typing import Any

from .. import db
from .registry import tool


@tool(
    name="get_schedule",
    description=(
        "指定日の予定を取得する。"
        "「今日の予定は？」「明日何ある？」のような発話で使う。"
        "date は YYYY-MM-DD。省略時は全件。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "date": {"type": "string", "description": "対象日 YYYY-MM-DD。省略可。"},
        },
    },
)
def get_schedule(date: str | None = None) -> dict[str, Any]:
    sql = "SELECT id, source, title, start_time, end_time, location FROM calendar_events_cache"
    params: list[Any] = []
    if date:
        sql += " WHERE start_time LIKE ?"
        params.append(f"{date}%")
    sql += " ORDER BY start_time ASC"
    with db.get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    events = [dict(r) for r in rows]
    return {"date": date, "count": len(events), "events": events}


@tool(
    name="add_schedule",
    description=(
        "新しい予定をローカルに追加する。"
        "「明日15時に歯医者を予定に入れて」のような発話で使う。"
        "start_time / end_time は ISO 形式または YYYY-MM-DD HH:MM 形式。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "予定のタイトル"},
            "start_time": {"type": "string", "description": "開始日時"},
            "end_time": {"type": "string", "description": "終了日時。任意。"},
            "location": {"type": "string", "description": "場所。任意。"},
            "description": {"type": "string", "description": "メモ。任意。"},
        },
        "required": ["title", "start_time"],
    },
)
def add_schedule(
    title: str,
    start_time: str,
    end_time: str | None = None,
    location: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    title = title.strip()
    start_time = start_time.strip()
    if not title:
        return {"added": False, "error": "title is required"}
    if not start_time:
        return {"added": False, "error": "start_time is required"}

    with db.get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO calendar_events_cache "
            "(source, title, start_time, end_time, location, description, updated_at) "
            "VALUES ('local', ?, ?, ?, ?, ?, ?)",
            (title, start_time, end_time, location, description, db.now_iso()),
        )
        event_id = int(cur.lastrowid)

    return {
        "added": True,
        "id": event_id,
        "title": title,
        "start_time": start_time,
        "end_time": end_time,
        "location": location,
        "description": description,
    }
