"""Discord-only channel reminders for both Owner mode and Guild mode."""
from __future__ import annotations

import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from . import config, db, discord_api

router = APIRouter()

_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SNOWFLAKE_RE = re.compile(r"^[0-9]{1,40}$")
DEFAULT_HOUR = 9
DEFAULT_MINUTE = 0

OWNER_SCHEMA = """
CREATE TABLE IF NOT EXISTS discord_reminders (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id     TEXT NOT NULL,
    guild_id       TEXT,
    author_id      TEXT NOT NULL,
    title          TEXT NOT NULL,
    message        TEXT NOT NULL,
    mention_target TEXT NOT NULL DEFAULT 'user',
    trigger_at     TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'scheduled',
    error          TEXT,
    created_at     TEXT NOT NULL,
    claimed_at     TEXT,
    sent_at        TEXT,
    cancelled_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_discord_reminders_due
ON discord_reminders(status, trigger_at, id);
"""

GUILD_REMINDER_SCHEMA = """
CREATE TABLE IF NOT EXISTS guild_reminders (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id     TEXT NOT NULL,
    author_id      TEXT NOT NULL,
    title          TEXT NOT NULL,
    message        TEXT NOT NULL,
    mention_target TEXT NOT NULL DEFAULT 'user',
    trigger_at     TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'scheduled',
    error          TEXT,
    created_at     TEXT NOT NULL,
    claimed_at     TEXT,
    sent_at        TEXT,
    cancelled_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_guild_reminders_due
ON guild_reminders(status, trigger_at, id);
"""


def default_timezone_name() -> str:
    return os.getenv("PETIT_TIMEZONE", "Asia/Tokyo").strip() or "Asia/Tokyo"


def _zone(tz_name: str | None = None) -> ZoneInfo:
    candidate = (tz_name or default_timezone_name()).strip() or "Asia/Tokyo"
    try:
        return ZoneInfo(candidate)
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        return ZoneInfo("Asia/Tokyo")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def normalize_mention_target(raw: str | None) -> str:
    val = str(raw or "user").strip().lower()
    if val in {"", "user", "author", "me", "self"}:
        return "user"
    if val in {"everyone", "@everyone", "all"}:
        return "everyone"
    raise ValueError("mention_target は 'user' または 'everyone' を指定してください。")


def parse_trigger_at(
    *,
    trigger_at: str | None = None,
    delay_minutes: int | None = None,
    tz_name: str | None = None,
    now: datetime | None = None,
) -> datetime:
    current = (now or _utc_now()).astimezone(timezone.utc)
    if delay_minutes is not None and trigger_at:
        raise ValueError("trigger_at と delay_minutes は同時に指定できません。")
    if delay_minutes is not None:
        if int(delay_minutes) < 1:
            raise ValueError("delay_minutes は 1 以上を指定してください。")
        if int(delay_minutes) > 525_600:
            raise ValueError("delay_minutes は 525600（1年）以内で指定してください。")
        return current + timedelta(minutes=int(delay_minutes))

    normalized = str(trigger_at or "").strip()
    if not normalized:
        raise ValueError("trigger_at または delay_minutes を指定してください。")
    tz = _zone(tz_name)
    if _DATE_ONLY_RE.match(normalized):
        parsed_date = datetime.strptime(normalized, "%Y-%m-%d").date()
        local_dt = datetime.combine(parsed_date, time(DEFAULT_HOUR, DEFAULT_MINUTE), tzinfo=tz)
        target = local_dt.astimezone(timezone.utc)
    else:
        if normalized.endswith("Z"):
            normalized = f"{normalized[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError(
                "trigger_at は '2026-12-01' または '2026-12-01T09:00:00+09:00' の形式で指定してください。"
            ) from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
        target = parsed.astimezone(timezone.utc)

    if target <= current - timedelta(seconds=5):
        raise ValueError("リマインド日時は未来の日時を指定してください。")
    return target


def _validate_snowflake(value: str, label: str) -> str:
    cleaned = str(value or "").strip()
    if not _SNOWFLAKE_RE.match(cleaned):
        raise ValueError(f"{label} が不正です。")
    return cleaned


def _prepare_fields(
    *,
    channel_id: str,
    author_id: str,
    title: str,
    message: str | None,
    mention_target: str | None,
    trigger_at: str | None,
    delay_minutes: int | None,
    tz_name: str | None,
) -> dict[str, str]:
    ch_id = _validate_snowflake(channel_id, "channel_id")
    au_id = _validate_snowflake(author_id, "author_id")
    norm_title = str(title or "").strip()
    if not norm_title:
        raise ValueError("リマインド内容（title）を指定してください。")
    if len(norm_title) > 160:
        norm_title = norm_title[:160]
    norm_msg = str(message or "").strip() or norm_title
    if len(norm_msg) > 1500:
        norm_msg = norm_msg[:1500]
    mention = normalize_mention_target(mention_target)
    trigger = parse_trigger_at(trigger_at=trigger_at, delay_minutes=delay_minutes, tz_name=tz_name)
    tz = _zone(tz_name)
    return {
        "channel_id": ch_id,
        "author_id": au_id,
        "title": norm_title,
        "message": norm_msg,
        "mention_target": mention,
        "trigger_at": _iso_utc(trigger),
        "trigger_at_local": trigger.astimezone(tz).isoformat(timespec="minutes"),
        "created_at": _iso_utc(_utc_now()),
    }


def ensure_owner_schema() -> None:
    with db.get_connection() as conn:
        conn.executescript(OWNER_SCHEMA)


def create_owner_reminder(
    *,
    channel_id: str,
    author_id: str,
    title: str,
    trigger_at: str | None = None,
    delay_minutes: int | None = None,
    message: str | None = None,
    mention_target: str = "user",
    guild_id: str | None = None,
    tz_name: str | None = None,
) -> dict[str, Any]:
    fields = _prepare_fields(
        channel_id=channel_id,
        author_id=author_id,
        title=title,
        message=message,
        mention_target=mention_target,
        trigger_at=trigger_at,
        delay_minutes=delay_minutes,
        tz_name=tz_name,
    )
    g_id = str(guild_id).strip() if guild_id else None
    if g_id and not _SNOWFLAKE_RE.match(g_id):
        raise ValueError("guild_id が不正です。")
    ensure_owner_schema()
    with db.write_transaction() as conn:
        cursor = conn.execute(
            "INSERT INTO discord_reminders(channel_id, guild_id, author_id, title, message, "
            "mention_target, trigger_at, status, created_at) VALUES(?,?,?,?,?,?,?,'scheduled',?)",
            (
                fields["channel_id"],
                g_id,
                fields["author_id"],
                fields["title"],
                fields["message"],
                fields["mention_target"],
                fields["trigger_at"],
                fields["created_at"],
            ),
        )
        row = conn.execute("SELECT * FROM discord_reminders WHERE id=?", (cursor.lastrowid,)).fetchone()
    item = dict(row)
    item["trigger_at_local"] = fields["trigger_at_local"]
    return item


def list_owner_reminders(
    *,
    channel_id: str | None = None,
    limit: int = 20,
    tz_name: str | None = None,
) -> list[dict[str, Any]]:
    ensure_owner_schema()
    tz = _zone(tz_name)
    bounded = max(1, min(int(limit), 50))
    where = ["status='scheduled'"]
    params: list[Any] = []
    if channel_id:
        where.append("channel_id=?")
        params.append(str(channel_id).strip())
    params.append(bounded)
    with db.get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM discord_reminders WHERE {' AND '.join(where)} ORDER BY trigger_at ASC, id ASC LIMIT ?",
            tuple(params),
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        try:
            dt = datetime.fromisoformat(item["trigger_at"])
            item["trigger_at_local"] = dt.astimezone(tz).isoformat(timespec="minutes")
        except ValueError:
            item["trigger_at_local"] = item["trigger_at"]
        items.append(item)
    return items


def cancel_owner_reminder(reminder_id: int, *, channel_id: str | None = None) -> dict[str, Any]:
    ensure_owner_schema()
    now = _iso_utc(_utc_now())
    with db.write_transaction() as conn:
        row = conn.execute("SELECT * FROM discord_reminders WHERE id=?", (int(reminder_id),)).fetchone()
        if row is None:
            raise ValueError("指定されたリマインダーが見つかりません。")
        if channel_id and row["channel_id"] != str(channel_id):
            raise ValueError("このチャンネルのリマインダーではありません。")
        if row["status"] != "scheduled":
            raise ValueError(f"状態が '{row['status']}' のためキャンセルできません。")
        conn.execute(
            "UPDATE discord_reminders SET status='cancelled', cancelled_at=? WHERE id=?",
            (now, int(reminder_id)),
        )
        updated = conn.execute("SELECT * FROM discord_reminders WHERE id=?", (int(reminder_id),)).fetchone()
    return dict(updated)


# ---------------------------------------------------------------- Guild DB helpers (no owner DB access)


def create_guild_reminder(
    conn: sqlite3.Connection,
    *,
    channel_id: str,
    author_id: str,
    title: str,
    trigger_at: str | None = None,
    delay_minutes: int | None = None,
    message: str | None = None,
    mention_target: str = "user",
    tz_name: str | None = None,
) -> dict[str, Any]:
    conn.executescript(GUILD_REMINDER_SCHEMA)
    fields = _prepare_fields(
        channel_id=channel_id,
        author_id=author_id,
        title=title,
        message=message,
        mention_target=mention_target,
        trigger_at=trigger_at,
        delay_minutes=delay_minutes,
        tz_name=tz_name,
    )
    cursor = conn.execute(
        "INSERT INTO guild_reminders(channel_id, author_id, title, message, mention_target, "
        "trigger_at, status, created_at) VALUES(?,?,?,?,?,?,'scheduled',?)",
        (
            fields["channel_id"],
            fields["author_id"],
            fields["title"],
            fields["message"],
            fields["mention_target"],
            fields["trigger_at"],
            fields["created_at"],
        ),
    )
    row = conn.execute("SELECT * FROM guild_reminders WHERE id=?", (cursor.lastrowid,)).fetchone()
    item = dict(row)
    item["trigger_at_local"] = fields["trigger_at_local"]
    return item


def list_guild_reminders(
    conn: sqlite3.Connection,
    *,
    channel_id: str | None = None,
    limit: int = 20,
    tz_name: str | None = None,
) -> list[dict[str, Any]]:
    conn.executescript(GUILD_REMINDER_SCHEMA)
    tz = _zone(tz_name)
    bounded = max(1, min(int(limit), 50))
    where = ["status='scheduled'"]
    params: list[Any] = []
    if channel_id:
        where.append("channel_id=?")
        params.append(str(channel_id).strip())
    params.append(bounded)
    rows = conn.execute(
        f"SELECT * FROM guild_reminders WHERE {' AND '.join(where)} ORDER BY trigger_at ASC, id ASC LIMIT ?",
        tuple(params),
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        try:
            dt = datetime.fromisoformat(item["trigger_at"])
            item["trigger_at_local"] = dt.astimezone(tz).isoformat(timespec="minutes")
        except ValueError:
            item["trigger_at_local"] = item["trigger_at"]
        items.append(item)
    return items


def cancel_guild_reminder(
    conn: sqlite3.Connection,
    reminder_id: int,
    *,
    author_id: str,
    channel_id: str | None = None,
    is_admin: bool = False,
) -> dict[str, Any]:
    conn.executescript(GUILD_REMINDER_SCHEMA)
    row = conn.execute("SELECT * FROM guild_reminders WHERE id=?", (int(reminder_id),)).fetchone()
    if row is None:
        raise ValueError("指定されたリマインダーが見つかりません。")
    if channel_id and row["channel_id"] != str(channel_id):
        raise ValueError("このチャンネルのリマインダーではありません。")
    if not is_admin and row["author_id"] != str(author_id):
        raise ValueError("他の人が登録したリマインダーはキャンセルできません。")
    if row["status"] != "scheduled":
        raise ValueError(f"状態が '{row['status']}' のためキャンセルできません。")
    now = _iso_utc(_utc_now())
    conn.execute(
        "UPDATE guild_reminders SET status='cancelled', cancelled_at=? WHERE id=?",
        (now, int(reminder_id)),
    )
    updated = conn.execute("SELECT * FROM guild_reminders WHERE id=?", (int(reminder_id),)).fetchone()
    return dict(updated)


# ---------------------------------------------------------------- Delivery endpoints


def _guilds_dir() -> Path:
    return config.STORAGE_DIR / "guilds"


def _guild_db_path(guild_id: str) -> Path:
    if not _SNOWFLAKE_RE.match(str(guild_id or "")):
        raise HTTPException(400, "guild_id が不正です。")
    base = _guilds_dir().resolve()
    target = (base / f"{guild_id}.db").resolve()
    if target.parent != base:
        raise HTTPException(400, "guild_id が不正です。")
    return target


def claim_due_reminders(*, limit: int = 20, now: datetime | None = None) -> list[dict[str, Any]]:
    """Claim due Discord channel reminders across Owner DB and enabled Guild DBs."""
    ensure_owner_schema()
    now_iso = _iso_utc(now or _utc_now())
    bounded = max(1, min(int(limit), 50))
    claimed: list[dict[str, Any]] = []

    with db.write_transaction() as conn:
        rows = conn.execute(
            "SELECT * FROM discord_reminders WHERE status='scheduled' AND trigger_at<=? "
            "ORDER BY trigger_at ASC, id ASC LIMIT ?",
            (now_iso, bounded),
        ).fetchall()
        for row in rows:
            conn.execute(
                "UPDATE discord_reminders SET status='claimed', claimed_at=? WHERE id=? AND status='scheduled'",
                (now_iso, row["id"]),
            )
            claimed.append({
                "scope": "owner",
                "guild_id": row["guild_id"],
                "reminder_id": int(row["id"]),
                "channel_id": row["channel_id"],
                "author_id": row["author_id"],
                "title": row["title"],
                "message": row["message"],
                "mention_target": row["mention_target"],
                "trigger_at": row["trigger_at"],
            })

    remaining = bounded - len(claimed)
    g_dir = _guilds_dir()
    if remaining > 0 and g_dir.is_dir():
        for db_file in sorted(g_dir.glob("*.db")):
            if remaining <= 0:
                break
            guild_id = db_file.stem
            if not _SNOWFLAKE_RE.match(guild_id):
                continue
            try:
                with closing(sqlite3.connect(db_file, timeout=5.0)) as conn:
                    conn.row_factory = sqlite3.Row
                    conn.execute("PRAGMA busy_timeout = 5000")
                    has_settings = conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE name='guild_settings'"
                    ).fetchone()
                    has_reminders = conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE name='guild_reminders'"
                    ).fetchone()
                    if not has_settings or not has_reminders:
                        continue
                    enabled_row = conn.execute(
                        "SELECT enabled FROM guild_settings WHERE guild_id=?", (guild_id,)
                    ).fetchone()
                    if not enabled_row or not enabled_row["enabled"]:
                        continue
                    with conn:
                        g_rows = conn.execute(
                            "SELECT * FROM guild_reminders WHERE status='scheduled' AND trigger_at<=? "
                            "ORDER BY trigger_at ASC, id ASC LIMIT ?",
                            (now_iso, remaining),
                        ).fetchall()
                        for row in g_rows:
                            conn.execute(
                                "UPDATE guild_reminders SET status='claimed', claimed_at=? "
                                "WHERE id=? AND status='scheduled'",
                                (now_iso, row["id"]),
                            )
                            claimed.append({
                                "scope": "guild",
                                "guild_id": guild_id,
                                "reminder_id": int(row["id"]),
                                "channel_id": row["channel_id"],
                                "author_id": row["author_id"],
                                "title": row["title"],
                                "message": row["message"],
                                "mention_target": row["mention_target"],
                                "trigger_at": row["trigger_at"],
                            })
                            remaining -= 1
            except sqlite3.Error:
                continue
    return claimed


@router.get("/api/channels/discord/reminders")
def claim_reminders_api(
    limit: int = Query(default=20, ge=1, le=50),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    discord_api._authorize(authorization)  # noqa: SLF001
    return {"reminders": claim_due_reminders(limit=limit)}


class ReminderDeliveryReport(BaseModel):
    status: str = Field(pattern=r"^(sent|failed)$")
    error: str | None = Field(default=None, max_length=500)
    guild_id: str | None = Field(default=None, max_length=40, pattern=r"^[0-9]+$")


@router.post("/api/channels/discord/reminders/{scope}/{reminder_id}")
def report_reminder_api(
    scope: str,
    reminder_id: int,
    body: ReminderDeliveryReport,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    discord_api._authorize(authorization)  # noqa: SLF001
    now_iso = _iso_utc(_utc_now())
    sent_at = now_iso if body.status == "sent" else None

    if scope == "owner":
        ensure_owner_schema()
        with db.write_transaction() as conn:
            updated = conn.execute(
                "UPDATE discord_reminders SET status=?, error=?, sent_at=? WHERE id=? AND status='claimed'",
                (body.status, body.error, sent_at, int(reminder_id)),
            ).rowcount
    elif scope == "guild":
        if not body.guild_id:
            raise HTTPException(400, "guild_id が必要です。")
        path = _guild_db_path(body.guild_id)
        if not path.is_file():
            raise HTTPException(404, "確保済みのリマインダーがありません。")
        with closing(sqlite3.connect(path, timeout=5.0)) as conn, conn:
            conn.execute("PRAGMA busy_timeout = 5000")
            updated = conn.execute(
                "UPDATE guild_reminders SET status=?, error=?, sent_at=? WHERE id=? AND status='claimed'",
                (body.status, body.error, sent_at, int(reminder_id)),
            ).rowcount
    else:
        raise HTTPException(400, "scope が不正です。")

    if not updated:
        raise HTTPException(404, "確保済みのリマインダーがありません。")
    return {"scope": scope, "reminder_id": reminder_id, "status": body.status}
