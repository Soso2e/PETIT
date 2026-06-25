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
