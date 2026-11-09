"""Discord Guild mode (D3): per-guild SQLite, DeepSeek-only chat, and budget.

Strict isolation guarantees:
- Guild data lives in ``storage/guilds/<guild_id>.db`` (never ``storage/app.db``).
- Guild mode runs with ``guild_mode()`` active in ``request_context``, which
  causes any attempt to access owner DB (``backend.db``), owner Tool Registry
  (``backend.tools.registry``), PETIT Home (``backend.petit_home``), or owner
  Brain / CLI (``backend.brain_priority``) to fail immediately.
- Brain is DeepSeek only. Unconfigured guilds make 0 DeepSeek calls.
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from . import config, discord_api, lmstudio_client, request_context, setup_store
from .petit_prompt import CORE_SYSTEM_PROMPT

router = APIRouter()
log = logging.getLogger(__name__)

GUILD_ID_RE = re.compile(r"^[0-9]{1,40}$")
MANAGE_GUILD_BIT = 0x20  # Discord permission flag: MANAGE_GUILD (1 << 5)

UNSET_GUIDE = (
    "このサーバーではまだプティのサーバー設定が行われていません。"
    "サーバーの管理者が `/petit setup` を実行すると使えるようになります。"
)
BUDGET_EXCEEDED_REPLY = "今日はここまでです。1日の利用上限に達したため、明日また話しかけてください。"
RATE_LIMITED_REPLY = "今日はここまでです。短時間に集中しているため、少し時間を置いてから話しかけてください。"

DEFAULT_TIMEZONE = "Asia/Tokyo"
DEFAULT_DAILY_CALL_LIMIT = 50
DEFAULT_DAILY_TOKEN_LIMIT = 60000
DEFAULT_USER_HOURLY_LIMIT = 15
HISTORY_LIMIT = 10
HISTORY_MAX_CHARS = 4000
MAX_REPLY_TOKENS = 800

GUILD_SYSTEM_PROMPT = (
    CORE_SYSTEM_PROMPT
    + "\n\n【Discord サーバー（Guild）モードの原則】\n"
    "- いまはサーバー共有のアシスタント（Guild モード）として話しています。\n"
    "- このサーバーの会話履歴と登録されたメンバー情報だけを使って答えてください。\n"
    "- PETIT の持ち主（owner）の個人データ・予定・タスク・記憶・開発環境には一切アクセスできません。\n"
    "- 簡潔で親しみやすい日本語で答えてください。\n"
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id            TEXT PRIMARY KEY,
    enabled             INTEGER NOT NULL DEFAULT 1,
    timezone            TEXT NOT NULL DEFAULT 'Asia/Tokyo',
    allowed_channels    TEXT NOT NULL DEFAULT '',
    reminder_channel_id TEXT,
    daily_call_limit    INTEGER NOT NULL DEFAULT 50,
    daily_token_limit   INTEGER NOT NULL DEFAULT 60000,
    user_hourly_limit   INTEGER NOT NULL DEFAULT 15,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS guild_members (
    user_id      TEXT PRIMARY KEY,
    display_name TEXT NOT NULL DEFAULT '',
    role_note    TEXT NOT NULL DEFAULT '',
    memo         TEXT NOT NULL DEFAULT '',
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS guild_conversations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id       TEXT NOT NULL UNIQUE,
    channel_id     TEXT NOT NULL,
    author_id      TEXT NOT NULL,
    user_text      TEXT NOT NULL,
    assistant_text TEXT NOT NULL,
    prompt_tokens  INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens   INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_guild_conv_channel ON guild_conversations(channel_id, id);
CREATE INDEX IF NOT EXISTS idx_guild_conv_author ON guild_conversations(author_id, id);

CREATE TABLE IF NOT EXISTS guild_usage_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id          TEXT NOT NULL UNIQUE,
    user_id           TEXT NOT NULL,
    day_key           TEXT NOT NULL,
    created_ts        REAL NOT NULL,
    prompt_tokens     INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_guild_usage_day ON guild_usage_log(day_key);
CREATE INDEX IF NOT EXISTS idx_guild_usage_user_ts ON guild_usage_log(user_id, created_ts);
"""


def guilds_dir() -> Path:
    return config.STORAGE_DIR / "guilds"


def db_path(guild_id: str) -> Path:
    if not isinstance(guild_id, str) or not GUILD_ID_RE.match(guild_id):
        raise HTTPException(400, "guild_id が不正です。")
    base = guilds_dir().resolve()
    target = (base / f"{guild_id}.db").resolve()
    if target.parent != base:
        raise HTTPException(400, "guild_id が不正です。")
    return target


def is_configured(guild_id: str) -> bool:
    path = db_path(guild_id)
    if not path.is_file():
        return False
    with closing(sqlite3.connect(path, timeout=5.0)) as conn:
        conn.row_factory = sqlite3.Row
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='guild_settings'").fetchone():
            return False
        row = conn.execute("SELECT enabled FROM guild_settings WHERE guild_id=?", (guild_id,)).fetchone()
        return bool(row and row["enabled"])


def _connect(guild_id: str, *, create: bool = False) -> sqlite3.Connection:
    path = db_path(guild_id)
    if not create and not path.is_file():
        raise FileNotFoundError(guild_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    if create:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
    return conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _valid_timezone(tz_name: str) -> str:
    name = (tz_name or DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        raise HTTPException(400, f"タイムゾーンが不正です: {name}") from None
    return name


def _day_key(tz_name: str) -> str:
    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001
        tz = timezone.utc
    return datetime.now(tz).strftime("%Y-%m-%d")


def _require_manage_guild(*, manage_guild: bool, permissions: int | None) -> None:
    has_perm = manage_guild or bool(permissions is not None and (permissions & MANAGE_GUILD_BIT))
    if not has_perm:
        raise HTTPException(403, "この操作にはサーバーの「サーバー管理（Manage Server）」権限が必要です。")


def _deepseek_target() -> dict[str, Any]:
    """Build DeepSeek target without touching brain_priority or owner Brain."""
    data = setup_store.load()
    key = data.get("secrets", {}).get(
        "deepseek_key",
        os.getenv("PETIT_DEEPSEEK_API_KEY", os.getenv("DEEPSEEK_API_KEY", "")),
    )
    model = data.get("deepseek_model") or "deepseek-chat"
    return {
        "provider": "deepseek",
        "profile": "guild_deepseek",
        "label": "DeepSeek",
        "external": True,
        "model": model,
        "base_url": "https://api.deepseek.com",
        "api_key": key,
        "configured": bool(key),
        "timeout_seconds": 60,
    }


def _redact_secrets(text: str, api_key: str) -> str:
    cleaned = str(text or "")
    if api_key and len(api_key) >= 4:
        cleaned = cleaned.replace(api_key, "[REDACTED]")
    for env_key in ("PETIT_DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY", "PETIT_DISCORD_SERVICE_TOKEN"):
        secret_val = os.getenv(env_key, "")
        if secret_val and len(secret_val) >= 4:
            cleaned = cleaned.replace(secret_val, "[REDACTED]")
    return cleaned


def call_deepseek(messages: list[dict[str, str]]) -> tuple[str, dict[str, int]]:
    """Call DeepSeek directly for Guild mode with tools=None. Never calls CLI or owner Brain."""
    if not request_context.is_guild_mode():
        raise RuntimeError("guild_deepseek_requires_guild_mode")
    target = _deepseek_target()
    api_key = str(target.get("api_key") or "")
    if not target["configured"]:
        raise lmstudio_client.LMStudioError("DeepSeek APIキーが設定されていないため、いまは返答できません。")
    try:
        with lmstudio_client.observe_turn() as metrics:
            response = lmstudio_client.chat_completion(
                messages,
                tools=None,
                temperature=0.5,
                max_tokens=MAX_REPLY_TOKENS,
                route="guild",
                target_override=target,
            )
            usage_list = (metrics or {}).get("usage") or []
            usage_raw = usage_list[-1] if usage_list else {}
    except Exception as exc:  # noqa: BLE001
        safe_msg = _redact_secrets(str(exc), api_key)
        log.warning("guild deepseek call failed: %s", type(exc).__name__)
        raise lmstudio_client.LMStudioError(safe_msg) from None

    if response.get("tool_calls"):
        raise lmstudio_client.LMStudioError("Guild モードでは Tool 呼び出しは許可されていません。")
    reply = _redact_secrets(str(response.get("content") or "").strip(), api_key)
    prompt_tokens = int(usage_raw.get("prompt_tokens") or 0)
    completion_tokens = int(usage_raw.get("completion_tokens") or 0)
    total_tokens = int(usage_raw.get("total_tokens") or (prompt_tokens + completion_tokens))
    if total_tokens <= 0:
        # Fallback estimate when provider omits token usage
        total_tokens = max(1, (sum(len(m.get("content", "")) for m in messages) + len(reply)) // 2)
    return reply, {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


class GuildSetupRequest(BaseModel):
    interaction_id: str = Field(default="0", min_length=1, max_length=40, pattern=r"^[0-9]+$")
    guild_id: str = Field(min_length=1, max_length=40, pattern=r"^[0-9]+$")
    author_id: str = Field(min_length=1, max_length=40, pattern=r"^[0-9]+$")
    manage_guild: bool = False
    permissions: int | None = None
    timezone: str = Field(default=DEFAULT_TIMEZONE, max_length=64)
    allowed_channels: list[str] = Field(default_factory=list, max_length=50)
    reminder_channel_id: str | None = Field(default=None, max_length=40, pattern=r"^[0-9]+$")
    daily_call_limit: int = Field(default=DEFAULT_DAILY_CALL_LIMIT, ge=1, le=10000)
    daily_token_limit: int = Field(default=DEFAULT_DAILY_TOKEN_LIMIT, ge=100, le=10_000_000)
    user_hourly_limit: int = Field(default=DEFAULT_USER_HOURLY_LIMIT, ge=1, le=1000)


class GuildResetRequest(BaseModel):
    interaction_id: str = Field(default="0", min_length=1, max_length=40, pattern=r"^[0-9]+$")
    guild_id: str = Field(min_length=1, max_length=40, pattern=r"^[0-9]+$")
    author_id: str = Field(min_length=1, max_length=40, pattern=r"^[0-9]+$")
    manage_guild: bool = False
    permissions: int | None = None


class GuildMemberRequest(BaseModel):
    interaction_id: str = Field(default="0", min_length=1, max_length=40, pattern=r"^[0-9]+$")
    guild_id: str = Field(min_length=1, max_length=40, pattern=r"^[0-9]+$")
    author_id: str = Field(min_length=1, max_length=40, pattern=r"^[0-9]+$")
    display_name: str = Field(default="", max_length=120)
    role_note: str = Field(default="", max_length=300)
    memo: str = Field(default="", max_length=1000)


class GuildMessageRequest(BaseModel):
    event_id: str = Field(min_length=1, max_length=40, pattern=r"^[0-9]+$")
    guild_id: str = Field(min_length=1, max_length=40, pattern=r"^[0-9]+$")
    channel_id: str = Field(min_length=1, max_length=40, pattern=r"^[0-9]+$")
    author_id: str = Field(min_length=1, max_length=40, pattern=r"^[0-9]+$")
    display_name: str = Field(default="", max_length=120)
    message: str = Field(min_length=1, max_length=20000)


@router.post("/api/guild/setup")
def setup_guild(body: GuildSetupRequest, authorization: str | None = Header(default=None)) -> dict:
    discord_api._authorize(authorization)
    _require_manage_guild(manage_guild=body.manage_guild, permissions=body.permissions)
    tz_name = _valid_timezone(body.timezone)
    for ch in body.allowed_channels:
        if not GUILD_ID_RE.match(ch):
            raise HTTPException(400, "allowed_channels のチャンネルIDが不正です。")
    channels_csv = ",".join(dict.fromkeys(body.allowed_channels))
    now = _now_iso()
    with request_context.guild_mode(guild_id=body.guild_id):
        with closing(_connect(body.guild_id, create=True)) as conn, conn:
            conn.execute(
                "INSERT INTO guild_settings("
                "guild_id,enabled,timezone,allowed_channels,reminder_channel_id,"
                "daily_call_limit,daily_token_limit,user_hourly_limit,created_at,updated_at"
                ") VALUES(?,1,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(guild_id) DO UPDATE SET "
                "enabled=1,timezone=excluded.timezone,allowed_channels=excluded.allowed_channels,"
                "reminder_channel_id=excluded.reminder_channel_id,"
                "daily_call_limit=excluded.daily_call_limit,daily_token_limit=excluded.daily_token_limit,"
                "user_hourly_limit=excluded.user_hourly_limit,updated_at=excluded.updated_at",
                (
                    body.guild_id,
                    tz_name,
                    channels_csv,
                    body.reminder_channel_id,
                    body.daily_call_limit,
                    body.daily_token_limit,
                    body.user_hourly_limit,
                    now,
                    now,
                ),
            )
    reply = (
        f"このサーバーでプティの Guild モードを有効にしました（タイムゾーン: {tz_name}、"
        f"1日上限: {body.daily_call_limit}回 / {body.daily_token_limit}トークン）。"
    )
    return {
        "mode": "guild",
        "status": "completed",
        "guild_id": body.guild_id,
        "enabled": True,
        "reply": reply,
    }


@router.post("/api/guild/reset")
def reset_guild(body: GuildResetRequest, authorization: str | None = Header(default=None)) -> dict:
    discord_api._authorize(authorization)
    _require_manage_guild(manage_guild=body.manage_guild, permissions=body.permissions)
    with request_context.guild_mode(guild_id=body.guild_id):
        path = db_path(body.guild_id)
        for suffix in ("", "-wal", "-shm"):
            Path(str(path) + suffix).unlink(missing_ok=True)
    return {
        "mode": "guild",
        "status": "completed",
        "guild_id": body.guild_id,
        "enabled": False,
        "reply": "このサーバーのプティ設定と保存データをすべて削除しました。",
    }


@router.post("/api/guild/me")
def member_me(body: GuildMemberRequest, authorization: str | None = Header(default=None)) -> dict:
    discord_api._authorize(authorization)
    with request_context.guild_mode(guild_id=body.guild_id):
        if not is_configured(body.guild_id):
            return {"mode": "guild", "status": "unconfigured", "reply": UNSET_GUIDE}
        now = _now_iso()
        with closing(_connect(body.guild_id)) as conn, conn:
            if body.display_name.strip() or body.role_note.strip() or body.memo.strip():
                existing = conn.execute(
                    "SELECT display_name,role_note,memo FROM guild_members WHERE user_id=?",
                    (body.author_id,),
                ).fetchone()
                name = body.display_name.strip() or (existing["display_name"] if existing else "")
                role = body.role_note.strip() or (existing["role_note"] if existing else "")
                memo = body.memo.strip() or (existing["memo"] if existing else "")
                conn.execute(
                    "INSERT INTO guild_members(user_id,display_name,role_note,memo,updated_at) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(user_id) DO UPDATE SET "
                    "display_name=excluded.display_name,role_note=excluded.role_note,memo=excluded.memo,updated_at=excluded.updated_at",
                    (body.author_id, name, role, memo, now),
                )
            member = conn.execute(
                "SELECT user_id,display_name,role_note,memo,updated_at FROM guild_members WHERE user_id=?",
                (body.author_id,),
            ).fetchone()
            recent = conn.execute(
                "SELECT user_text,assistant_text,created_at FROM guild_conversations "
                "WHERE author_id=? ORDER BY id DESC LIMIT 5",
                (body.author_id,),
            ).fetchall()
            conv_count = conn.execute(
                "SELECT COUNT(*) FROM guild_conversations WHERE author_id=?",
                (body.author_id,),
            ).fetchone()[0]

    lines: list[str] = []
    if member and (member["display_name"] or member["role_note"] or member["memo"]):
        if member["display_name"]:
            lines.append(f"・呼び名: {member['display_name']}")
        if member["role_note"]:
            lines.append(f"・担当: {member['role_note']}")
        if member["memo"]:
            lines.append(f"・メモ: {member['memo']}")
    if conv_count:
        lines.append(f"・このサーバーでの会話記録: {conv_count}件")
        for row in reversed(recent[:3]):
            lines.append(f"  - 「{row['user_text'][:60]}」")
    if not lines:
        reply = "このサーバーでは、あなたについてまだ何も記録していません。"
    else:
        reply = "このサーバーで覚えているあなたのこと:\n" + "\n".join(lines)
    return {
        "mode": "guild",
        "status": "completed",
        "profile": dict(member) if member else None,
        "conversation_count": conv_count,
        "reply": reply,
    }


@router.post("/api/guild/forget-me")
def forget_me(body: GuildMemberRequest, authorization: str | None = Header(default=None)) -> dict:
    discord_api._authorize(authorization)
    with request_context.guild_mode(guild_id=body.guild_id):
        path = db_path(body.guild_id)
        if not path.is_file():
            return {
                "mode": "guild",
                "status": "completed",
                "deleted": False,
                "reply": "このサーバーにあなたの記録はありません。",
            }
        with closing(_connect(body.guild_id)) as conn, conn:
            m_deleted = conn.execute("DELETE FROM guild_members WHERE user_id=?", (body.author_id,)).rowcount
            c_deleted = conn.execute("DELETE FROM guild_conversations WHERE author_id=?", (body.author_id,)).rowcount
        return {
            "mode": "guild",
            "status": "completed",
            "deleted": bool(m_deleted or c_deleted),
            "reply": "このサーバーに保存されていたあなたのプロフィールと会話記録をすべて消去しました。",
        }


def handle_mention(body: GuildMessageRequest) -> dict:
    """Process a guild mention strictly in Guild mode using only the guild's SQLite and DeepSeek."""
    with request_context.guild_mode(guild_id=body.guild_id):
        if not is_configured(body.guild_id):
            return {"mode": "guest", "status": "completed", "reply": discord_api.GUEST_GUIDE, "approvals": []}

        with closing(_connect(body.guild_id)) as conn:
            settings_row = conn.execute(
                "SELECT * FROM guild_settings WHERE guild_id=?", (body.guild_id,)
            ).fetchone()
            if not settings_row or not settings_row["enabled"]:
                return {"mode": "guest", "status": "completed", "reply": discord_api.GUEST_GUIDE, "approvals": []}

            # Idempotency: if this Discord event_id was already answered, return saved reply without calling DeepSeek.
            existing = conn.execute(
                "SELECT assistant_text FROM guild_conversations WHERE event_id=?",
                (body.event_id,),
            ).fetchone()
            if existing is not None:
                return {
                    "mode": "guild",
                    "status": "completed",
                    "reply": existing["assistant_text"],
                    "request_id": f"guild:{body.guild_id}:{body.event_id}",
                    "approvals": [],
                }

            allowed = [c.strip() for c in (settings_row["allowed_channels"] or "").split(",") if c.strip()]
            if allowed and body.channel_id not in allowed:
                return {
                    "mode": "guild",
                    "status": "ignored_channel",
                    "reply": "このチャンネルでは応答しない設定になっています。",
                    "approvals": [],
                }

            day_key = _day_key(settings_row["timezone"])
            now_ts = time.time()

            # Check server daily call/token budget
            day_usage = conn.execute(
                "SELECT COUNT(*) AS calls, COALESCE(SUM(total_tokens), 0) AS tokens "
                "FROM guild_usage_log WHERE day_key=?",
                (day_key,),
            ).fetchone()
            if (
                int(day_usage["calls"] or 0) >= int(settings_row["daily_call_limit"])
                or int(day_usage["tokens"] or 0) >= int(settings_row["daily_token_limit"])
            ):
                return {
                    "mode": "guild",
                    "status": "budget_exceeded",
                    "reply": BUDGET_EXCEEDED_REPLY,
                    "approvals": [],
                }

            # Check per-user hourly rate limit
            user_calls = conn.execute(
                "SELECT COUNT(*) AS calls FROM guild_usage_log WHERE user_id=? AND created_ts>=?",
                (body.author_id, now_ts - 3600.0),
            ).fetchone()
            if int(user_calls["calls"] or 0) >= int(settings_row["user_hourly_limit"]):
                return {
                    "mode": "guild",
                    "status": "rate_limited",
                    "reply": RATE_LIMITED_REPLY,
                    "approvals": [],
                }

            # Build guild-only context (member profiles + recent channel conversations in this guild DB)
            members = conn.execute(
                "SELECT user_id,display_name,role_note,memo FROM guild_members ORDER BY updated_at DESC LIMIT 20"
            ).fetchall()
            history_rows = conn.execute(
                "SELECT author_id,user_text,assistant_text FROM guild_conversations "
                "WHERE channel_id=? ORDER BY id DESC LIMIT ?",
                (body.channel_id, HISTORY_LIMIT),
            ).fetchall()

        messages: list[dict[str, str]] = [{"role": "system", "content": GUILD_SYSTEM_PROMPT}]
        if members:
            member_lines = []
            for m in members:
                label = m["display_name"] or f"user:{m['user_id']}"
                parts = [p for p in (m["role_note"], m["memo"]) if p]
                member_lines.append(f"- {label} (ID: {m['user_id']})" + (f": {' / '.join(parts)}" if parts else ""))
            messages.append({
                "role": "system",
                "content": "このサーバーのメンバー情報:\n" + "\n".join(member_lines),
            })

        budget_chars = HISTORY_MAX_CHARS
        history_msgs: list[dict[str, str]] = []
        for row in history_rows:
            a_text = str(row["assistant_text"] or "").strip()
            u_text = str(row["user_text"] or "").strip()
            if a_text and budget_chars > 0:
                clipped_a = a_text[-budget_chars:]
                history_msgs.append({"role": "assistant", "content": clipped_a})
                budget_chars -= len(clipped_a)
            if u_text and budget_chars > 0:
                clipped_u = u_text[-budget_chars:]
                history_msgs.append({"role": "user", "content": clipped_u})
                budget_chars -= len(clipped_u)
        messages.extend(reversed(history_msgs))

        speaker_prefix = f"[{body.display_name.strip()}] " if body.display_name.strip() else ""
        messages.append({"role": "user", "content": f"{speaker_prefix}{body.message}"})

        try:
            reply, usage = call_deepseek(messages)
        except lmstudio_client.LMStudioError as exc:
            return {
                "mode": "guild",
                "status": "failed",
                "reply": str(exc) or "うまく処理できませんでした。",
                "approvals": [],
            }

        now = _now_iso()
        with closing(_connect(body.guild_id)) as conn, conn:
            if body.display_name.strip():
                conn.execute(
                    "INSERT INTO guild_members(user_id,display_name,role_note,memo,updated_at) VALUES(?,?,'','',?) "
                    "ON CONFLICT(user_id) DO UPDATE SET "
                    "display_name=CASE WHEN guild_members.display_name='' THEN excluded.display_name ELSE guild_members.display_name END",
                    (body.author_id, body.display_name.strip(), now),
                )
            conn.execute(
                "INSERT OR IGNORE INTO guild_conversations("
                "event_id,channel_id,author_id,user_text,assistant_text,"
                "prompt_tokens,completion_tokens,total_tokens,created_at"
                ") VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    body.event_id,
                    body.channel_id,
                    body.author_id,
                    body.message,
                    reply,
                    usage["prompt_tokens"],
                    usage["completion_tokens"],
                    usage["total_tokens"],
                    now,
                ),
            )
            conn.execute(
                "INSERT OR IGNORE INTO guild_usage_log("
                "event_id,user_id,day_key,created_ts,prompt_tokens,completion_tokens,total_tokens"
                ") VALUES(?,?,?,?,?,?,?)",
                (
                    body.event_id,
                    body.author_id,
                    day_key,
                    now_ts,
                    usage["prompt_tokens"],
                    usage["completion_tokens"],
                    usage["total_tokens"],
                ),
            )

        return {
            "mode": "guild",
            "status": "completed",
            "reply": reply,
            "request_id": f"guild:{body.guild_id}:{body.event_id}",
            "approvals": [],
        }


@router.post("/api/guild/messages")
def receive_guild_message(body: GuildMessageRequest, authorization: str | None = Header(default=None)) -> dict:
    discord_api._authorize(authorization)
    return handle_mention(body)


@router.get("/api/guild/{guild_id}/usage")
def guild_usage(guild_id: str, authorization: str | None = Header(default=None)) -> dict:
    discord_api._authorize(authorization)
    with request_context.guild_mode(guild_id=guild_id):
        if not is_configured(guild_id):
            raise HTTPException(404, "このサーバーは未設定です。")
        with closing(_connect(guild_id)) as conn:
            settings_row = conn.execute(
                "SELECT * FROM guild_settings WHERE guild_id=?", (guild_id,)
            ).fetchone()
            day_key = _day_key(settings_row["timezone"])
            day_usage = conn.execute(
                "SELECT COUNT(*) AS calls, COALESCE(SUM(total_tokens), 0) AS tokens "
                "FROM guild_usage_log WHERE day_key=?",
                (day_key,),
            ).fetchone()
        return {
            "guild_id": guild_id,
            "day": day_key,
            "calls_today": int(day_usage["calls"] or 0),
            "tokens_today": int(day_usage["tokens"] or 0),
            "daily_call_limit": int(settings_row["daily_call_limit"]),
            "daily_token_limit": int(settings_row["daily_token_limit"]),
            "user_hourly_limit": int(settings_row["user_hourly_limit"]),
        }
