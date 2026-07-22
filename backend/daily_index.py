"""Once-per-day life index built from PETIT conversation history.

Conversation turns stay untouched in SQLite.  At the end of each local day PETIT
sends almost every user turn to the configured local LM Studio endpoint, stores a
structured index in SQLite, mirrors it to Markdown, and exposes it to the existing
memory search by writing one generated ``daily_index`` memory item.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from . import chroma_client, config, db

log = logging.getLogger(__name__)

_COLLECTION_FIELDS = (
    "events",
    "activities",
    "foods",
    "people",
    "places",
    "emotions",
    "projects",
    "memory_candidates",
    "uncertain",
)
_TEXT_SIGNAL = re.compile(r"[A-Za-z0-9一-龯々〆ヵヶぁ-んァ-ヶー]")
_SYSTEM_PROMPT = (
    "PETITの日次生活索引を作る。会話に明記された事実だけを使い、推測しない。"
    "予定・希望・仮定・否定は実績にせずuncertainへ入れる。雑談の外出、食事、人間関係、"
    "感情、買物、健康、制作、開発、学習も拾う。長期記憶候補はmemory_candidatesへ入れるが"
    "確定記憶にはしない。JSONだけ返す。形式:"
    '{"summary":"","events":[],"activities":[],"foods":[],"people":[],"places":[],"
    emotions":[],"projects":[],"memory_candidates":[],"uncertain":[]}'
)


class DailyIndexError(RuntimeError):
    """Raised when the local daily-index model cannot return a valid result."""


def _timezone() -> ZoneInfo:
    try:
        return ZoneInfo(config.DAILY_INDEX_TIMEZONE)
    except ZoneInfoNotFoundError:
        log.warning("Unknown daily index timezone %s; falling back to UTC", config.DAILY_INDEX_TIMEZONE)
        return ZoneInfo("UTC")


def due_day(now: datetime | None = None) -> date:
    """Latest local day whose configured end-of-day job is due."""
    local_now = (now or datetime.now(timezone.utc)).astimezone(_timezone())
    scheduled = datetime.combine(
        local_now.date(),
        time(config.DAILY_INDEX_HOUR, config.DAILY_INDEX_MINUTE),
        tzinfo=_timezone(),
    )
    days_back = 1 if local_now >= scheduled else 2
    return local_now.date() - timedelta(days=days_back)


def _day_bounds(day: date) -> tuple[str, str]:
    tz = _timezone()
    start = datetime.combine(day, time.min, tzinfo=tz).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz).astimezone(timezone.utc)
    return start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")


def ensure_schema() -> None:
    with db.get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_indexes (
                day TEXT PRIMARY KEY,
                timezone TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                status TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                source_conversation_ids TEXT NOT NULL DEFAULT '[]',
                content_hash TEXT,
                error TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_daily_indexes_status ON daily_indexes(status, day)")


def _existing(day: str) -> dict[str, Any] | None:
    ensure_schema()
    with db.get_connection() as conn:
        row = conn.execute("SELECT * FROM daily_indexes WHERE day = ?", (day,)).fetchone()
    return dict(row) if row else None


def _rows_for_day(day: date) -> list[dict[str, Any]]:
    start, end = _day_bounds(day)
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT id, timestamp, user_text, assistant_text, used_tools, session_id "
            "FROM conversations WHERE timestamp >= ? AND timestamp < ? ORDER BY id ASC",
            (start, end),
        ).fetchall()
    return [dict(row) for row in rows]


def _has_text_signal(value: str) -> bool:
    return bool(_TEXT_SIGNAL.search(value))


def _compact_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop only certain noise: empty/symbol-only turns and consecutive duplicates."""
    compact: list[dict[str, Any]] = []
    previous_user: str | None = None
    for row in rows:
        user = " ".join(str(row.get("user_text") or "").split())
        if not user or not _has_text_signal(user):
            continue
        normalized = user.casefold()
        if normalized == previous_user:
            continue
        previous_user = normalized
        assistant = " ".join(str(row.get("assistant_text") or "").split())
        if len(assistant) > config.DAILY_INDEX_ASSISTANT_MAX_CHARS:
            assistant = assistant[: config.DAILY_INDEX_ASSISTANT_MAX_CHARS] + "…"
        compact.append(
            {
                "id": int(row["id"]),
                "timestamp": str(row["timestamp"]),
                "user": user,
                "assistant": assistant,
                "tools": str(row.get("used_tools") or ""),
                "session_id": str(row.get("session_id") or "legacy"),
            }
        )
    return compact


def _entry_text(row: dict[str, Any]) -> str:
    tool = f" tools={row['tools']}" if row["tools"] else ""
    return (
        f"[{row['timestamp']}] session={row['session_id']}{tool}\n"
        f"ユーザー: {row['user']}\nPETIT: {row['assistant']}"
    )


def _chunks(rows: list[dict[str, Any]]) -> list[str]:
    limit = max(1000, int(config.DAILY_INDEX_MAX_INPUT_CHARS))
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0
    for row in rows:
        entry = _entry_text(row)
        if current and current_size + len(entry) + 2 > limit:
            chunks.append("\n\n".join(current))
            current = []
            current_size = 0
        current.append(entry)
        current_size += len(entry) + 2
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _extract_json(text: str) -> dict[str, Any] | None:
    candidate = str(text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", candidate, re.S)
    if fenced:
        candidate = fenced.group(1)
    elif not candidate.startswith("{"):
        start, end = candidate.find("{"), candidate.rfind("}")
        candidate = candidate[start : end + 1] if start >= 0 and end > start else ""
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = " ".join(str(item or "").split())
        if text and text not in out:
            out.append(text)
    return out


def _normalize_payload(value: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {"summary": " ".join(str(value.get("summary") or "").split())}
    for field in _COLLECTION_FIELDS:
        payload[field] = _items(value.get(field))
    return payload


def _call_local(transcript: str) -> dict[str, Any]:
    url = f"{config.DAILY_INDEX_BASE_URL.rstrip('/')}/chat/completions"
    payload = {
        "model": config.DAILY_INDEX_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": transcript},
        ],
        "temperature": 0.1,
        "max_tokens": config.DAILY_INDEX_MAX_TOKENS,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    headers = {"Authorization": f"Bearer {config.DAILY_INDEX_API_KEY}"}
    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=config.LM_TIMEOUT)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise DailyIndexError(f"local daily index model failed: {exc}") from exc
    parsed = _extract_json(str(content or ""))
    if parsed is None:
        raise DailyIndexError("local daily index model returned invalid JSON")
    return _normalize_payload(parsed)


def _merge_payloads(values: list[dict[str, Any]]) -> dict[str, Any]:
    summaries: list[str] = []
    merged: dict[str, Any] = {"summary": ""}
    for field in _COLLECTION_FIELDS:
        merged[field] = []
    for value in values:
        summary = str(value.get("summary") or "").strip()
        if summary and summary not in summaries:
            summaries.append(summary)
        for field in _COLLECTION_FIELDS:
            for item in _items(value.get(field)):
                if item not in merged[field]:
                    merged[field].append(item)
    merged["summary"] = " ".join(summaries)
    return merged


def _index_text(day: str, payload: dict[str, Any]) -> str:
    labels = {
        "events": "出来事",
        "activities": "活動",
        "foods": "食事",
        "people": "人",
        "places": "場所",
        "emotions": "感情",
        "projects": "プロジェクト",
        "memory_candidates": "長期記憶候補",
        "uncertain": "予定・未確定",
    }
    lines = [f"{day} 日次生活インデックス", f"概要: {payload.get('summary') or 'なし'}"]
    for field, label in labels.items():
        values = _items(payload.get(field))
        if values:
            lines.append(f"{label}: " + " / ".join(values))
    return "\n".join(lines)


def _write_markdown(day: str, payload: dict[str, Any], source_ids: list[int]) -> bool:
    try:
        config.AI_DAILY_DIR.mkdir(parents=True, exist_ok=True)
        path = config.AI_DAILY_DIR / f"{day}-index.md"
        labels = {
            "events": "出来事",
            "activities": "活動",
            "foods": "食事",
            "people": "人",
            "places": "場所",
            "emotions": "感情",
            "projects": "プロジェクト",
            "memory_candidates": "長期記憶候補（未確定）",
            "uncertain": "予定・未確定",
        }
        lines = [
            "---",
            "type: petit_daily_index",
            f"date: {day}",
            f"timezone: {config.DAILY_INDEX_TIMEZONE}",
            "tags: [petit, daily-index]",
            "---",
            "",
            f"# {day} 日次生活インデックス",
            "",
            "## 概要",
            "",
            str(payload.get("summary") or "記録なし"),
            "",
        ]
        for field, label in labels.items():
            lines.extend([f"## {label}", ""])
            values = _items(payload.get(field))
            lines.extend([f"- {item}" for item in values] or ["- なし"])
            lines.append("")
        lines.extend(["## 元会話ID", "", ", ".join(str(item) for item in source_ids) or "なし", ""])
        temporary = path.with_suffix(".md.tmp")
        temporary.write_text("\n".join(lines), encoding="utf-8")
        temporary.replace(path)
        return True
    except Exception as exc:  # noqa: BLE001
        log.debug("daily index markdown export failed: %s", exc)
        return False


def _save_generated(day: str, payload: dict[str, Any], source_ids: list[int]) -> tuple[int, str]:
    text = _index_text(day, payload)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    now = db.now_iso()
    source = f"daily_index:{day}"
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO daily_indexes(day, timezone, generated_at, status, summary, payload_json, source_conversation_ids, content_hash, error) "
            "VALUES (?, ?, ?, 'generated', ?, ?, ?, ?, NULL) "
            "ON CONFLICT(day) DO UPDATE SET timezone=excluded.timezone, generated_at=excluded.generated_at, "
            "status='generated', summary=excluded.summary, payload_json=excluded.payload_json, "
            "source_conversation_ids=excluded.source_conversation_ids, content_hash=excluded.content_hash, error=NULL",
            (
                day,
                config.DAILY_INDEX_TIMEZONE,
                now,
                str(payload.get("summary") or ""),
                json.dumps(payload, ensure_ascii=False),
                json.dumps(source_ids),
                digest,
            ),
        )
        row = conn.execute(
            "SELECT id FROM memory WHERE type = 'daily_index' AND source = ? ORDER BY id ASC LIMIT 1",
            (source,),
        ).fetchone()
        if row:
            memory_id = int(row["id"])
            conn.execute(
                "UPDATE memory SET created_at=?, content=?, content_hash=?, embedding_model=NULL, "
                "embedding_version=NULL, indexed_at=NULL WHERE id=?",
                (now, text, digest, memory_id),
            )
        else:
            cur = conn.execute(
                "INSERT INTO memory(created_at, type, content, source, content_hash) VALUES (?, 'daily_index', ?, ?, ?)",
                (now, text, source, digest),
            )
            memory_id = int(cur.lastrowid)
    return memory_id, text


def _save_status(day: str, status: str, *, error: str | None = None) -> None:
    ensure_schema()
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO daily_indexes(day, timezone, generated_at, status, error) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(day) DO UPDATE SET timezone=excluded.timezone, generated_at=excluded.generated_at, "
            "status=excluded.status, error=excluded.error",
            (day, config.DAILY_INDEX_TIMEZONE, db.now_iso(), status, error),
        )


def generate(day: str | date | None = None, *, force: bool = False) -> dict[str, Any]:
    """Generate one local-day index. Existing successful days are idempotent."""
    ensure_schema()
    target = due_day() if day is None else (date.fromisoformat(day) if isinstance(day, str) else day)
    key = target.isoformat()
    existing = _existing(key)
    if existing and existing.get("status") in {"generated", "empty"} and not force:
        return {"generated": False, "reason": "already_indexed", "day": key, "status": existing["status"]}

    rows = _compact_rows(_rows_for_day(target))
    if not rows:
        _save_status(key, "empty")
        return {"generated": False, "reason": "no_conversations", "day": key, "status": "empty"}

    try:
        payload = _merge_payloads([_call_local(chunk) for chunk in _chunks(rows)])
    except DailyIndexError as exc:
        if not existing or existing.get("status") != "generated":
            _save_status(key, "failed", error=str(exc))
        return {"generated": False, "reason": "local_llm_unavailable", "day": key, "error": str(exc)}

    source_ids = [int(row["id"]) for row in rows]
    memory_id, _text = _save_generated(key, payload, source_ids)
    markdown_saved = _write_markdown(key, payload, source_ids)
    indexed = chroma_client.sync_structured_data(db.all_memory(), db.all_episodes()).get("memory", 0)
    return {
        "generated": True,
        "day": key,
        "conversation_count": len(rows),
        "chunk_count": len(_chunks(rows)),
        "memory_id": memory_id,
        "markdown_saved": markdown_saved,
        "indexed_count": indexed,
        "payload": payload,
    }


def recent(limit: int = 10) -> list[dict[str, Any]]:
    ensure_schema()
    bounded = max(1, min(int(limit), 100))
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT day, timezone, generated_at, status, summary, payload_json, source_conversation_ids, error "
            "FROM daily_indexes ORDER BY day DESC LIMIT ?",
            (bounded,),
        ).fetchall()
    return [dict(row) for row in rows]


def status() -> dict[str, Any]:
    rows = recent(limit=1)
    return {
        "enabled": bool(config.AUTO_SUMMARY_ENABLED),
        "timezone": config.DAILY_INDEX_TIMEZONE,
        "run_at": f"{config.DAILY_INDEX_HOUR:02d}:{config.DAILY_INDEX_MINUTE:02d}",
        "local_model": config.DAILY_INDEX_MODEL,
        "last": rows[0] if rows else None,
    }
