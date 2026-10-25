"""Schedule tools.

MVP reads a local SQLite calendar cache. Real calendar sources (Google /
Apple Calendar) can populate calendar_events_cache later.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .. import calendar_providers, calendar_sync, db
from .registry import tool


def _query_variants(query: str) -> list[str]:
    """Search literal terms, with known Japanese/English event-name aliases."""
    term = query.strip()
    if not term:
        return []
    aliases = {"capcom": "カプコン", "カプコン": "CAPCOM"}
    alias = aliases.get(term.casefold())
    return [term, alias] if alias else [term]


def _like_literal(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


@tool(
    name="get_schedule",
    description=(
        "指定日またはキーワードに一致する予定をカレンダーキャッシュから取得する。"
        "「今日の予定は？」はdate、「CAPCOMのMTGはいつ？」はqueryを指定する。"
        "dateはYYYY-MM-DD、queryは予定名などの検索語。両方指定可。"
        "dateもqueryもない場合は全件取得するため、検索ではqueryを必ず渡す。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "date": {"type": "string", "description": "対象日 YYYY-MM-DD。省略可。"},
            "query": {"type": "string", "description": "予定名・説明・場所から検索する語。日付が不明ならこちらを指定。"},
        },
    },
)
def get_schedule(date: str | None = None, query: str | None = None) -> dict[str, Any]:
    sync_status = calendar_sync.sync_if_configured()
    sql = "SELECT id, source, title, start_time, end_time, location FROM calendar_events_cache"
    filters: list[str] = []
    params: list[Any] = []
    from .. import setup_store, service_sync
    if setup_store.initialized():
        key = service_sync.source_key()
        filters.append("(source = 'local' OR source_key = ?)")
        params.append(key)
    if date:
        filters.append("start_time LIKE ?")
        params.append(f"{date}%")
    terms = _query_variants(query or "")
    if terms:
        columns = ("title", "description", "location")
        matches = []
        for term in terms:
            matches.append("(" + " OR ".join(
                f"{column} LIKE ? ESCAPE '\\' COLLATE NOCASE" for column in columns
            ) + ")")
            params.extend([_like_literal(term)] * len(columns))
        filters.append("(" + " OR ".join(matches) + ")")
    if filters:
        sql += " WHERE " + " AND ".join(filters)
    if terms and not date:
        # Keep future meetings visible even when years of historical events exist.
        sql += " ORDER BY CASE WHEN substr(start_time, 1, 10) >= ? THEN 0 ELSE 1 END, start_time ASC"
        params.append(datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat())
    else:
        sql += " ORDER BY start_time ASC"
    with db.get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    events = [dict(r) for r in rows]
    return {"date": date, "query": query if terms else None, "count": len(events),
            "events": events, "calendar_sync": sync_status}


@tool(
    name="add_schedule",
    description=(
        "新しい予定をPETITのローカル予定へ追加する。ICS/Google Calendar本体には書き込まない。"
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
            "destination": {
                "type": "string",
                "description": "書き込み先。現在はlocalのみ。将来google_calendarアダプターを追加可能。",
                "default": "local",
            },
        },
        "required": ["title", "start_time"],
    },
    requires_confirmation=True,
)
def add_schedule(
    title: str,
    start_time: str,
    end_time: str | None = None,
    location: str | None = None,
    description: str | None = None,
    destination: str = "local",
) -> dict[str, Any]:
    title = title.strip()
    start_time = start_time.strip()
    if not title:
        return {"added": False, "error": "title is required"}
    if not start_time:
        return {"added": False, "error": "start_time is required"}

    return calendar_providers.add_event(
        destination=destination,
        title=title,
        start_time=start_time,
        end_time=end_time,
        location=location,
        description=description,
    )


@tool(
    name="sync_calendar",
    description=(
        "設定済みのGoogle Calendar iCal/ICS URLまたはローカル.icsファイルから、"
        "予定キャッシュを読み取り専用で同期する。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "force": {"type": "boolean", "description": "TTLを無視して再同期するか。既定はtrue。"},
        },
    },
)
def sync_calendar(force: bool = True) -> dict[str, Any]:
    return calendar_sync.sync_if_configured(force=force)
