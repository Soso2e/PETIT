"""Daily progress posts to Discord (#504).

The owner registers a channel, forum or thread with ``/petit digest``. Every day at the
registered local time Core builds the Life Log digest (``life_log.generate``) and queues a
post; the Bot claims queued posts and sends them (a forum gets a new post per day).

Delivery states follow the notification rules (Concept §8): ``ready`` -> ``claimed`` ->
``sent`` / ``failed``. A claim that never reports back stays ``claimed`` (unknown) and is
not re-sent automatically. One post per subscription and day (UNIQUE), so restarts and
overlapping ticks never post twice.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from . import db, discord_api, life_log

log = logging.getLogger(__name__)
router = APIRouter()

CATCHUP = timedelta(hours=6)
TIME_RE = re.compile(r"^([01]?\d|2[0-3])[:：]([0-5]\d)$")
DAY_OFFSETS = {"yesterday": 1, "today": 0}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS discord_digest_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT NOT NULL UNIQUE,
    guild_id TEXT,
    hour INTEGER NOT NULL,
    minute INTEGER NOT NULL,
    timezone TEXT NOT NULL,
    day_offset INTEGER NOT NULL DEFAULT 1,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS discord_digest_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    status TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    claimed_at TEXT,
    sent_at TEXT,
    UNIQUE(subscription_id, day)
);
"""


def ensure_schema() -> None:
    with db.get_connection() as conn:
        conn.executescript(_SCHEMA)


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(400, f"タイムゾーンが不正です: {name}") from None


def _parse_time(value: str) -> tuple[int, int]:
    match = TIME_RE.match((value or "").strip())
    if not match:
        raise HTTPException(400, "時刻は 10:00 のように HH:MM で指定してください。")
    return int(match.group(1)), int(match.group(2))


def _require_owner(author_id: str, guild_id: str | None) -> None:
    probe = discord_api.DiscordEvent(event_id="0", channel_id="0", guild_id=guild_id, author_id=author_id, message="-")
    if discord_api.mode_for(probe) != "owner":
        raise HTTPException(403, "進捗投稿の設定は PETIT の持ち主だけが、DM か指定サーバーで行えます。")


def audience_for(guild_id: str | None) -> str:
    """A DM is private; a server channel can be read by others, so it gets work-only content."""
    return "shared" if guild_id else "private"


def _failure_reason(digest: dict) -> str:
    status = digest.get("status")
    diag = digest.get("diagnostics") or {}
    if status == "empty":
        if diag.get("audience") == "shared" and (
            diag.get("dropped_by_shared") or diag.get("facts_dropped_by_shared")
        ):
            return "情報不足（サーバーチャンネル用の公開フィルタにより個人記録が除外された）"
        return "情報不足（載せられる記録がない）"
    if status == "degraded":
        stages = digest.get("stages") or {}
        failed = [name for name in ("extract", "merge", "compose") if stages.get(name) == "fallback"]
        if diag and not diag.get("llm_configured", True):
            return "要約に失敗: DeepSeek API が未設定"
        return "要約に失敗: " + ("/".join(failed) or "不明")
    return "生成に失敗: " + str(digest.get("error") or status)


def _preview_diagnostics(digest: dict) -> list[str]:
    diag = digest.get("diagnostics") or {}
    if not diag:
        return []
    notes: list[str] = []
    raw_sources = diag.get("raw_sources") or {}
    if raw_sources:
        summary = ", ".join(f"{k}={v}件" for k, v in sorted(raw_sources.items()))
        notes.append(f"取得できた記録: {summary}")
    else:
        notes.append("取得できた記録: 0件（どのソースからも対象日の記録が見つかりませんでした）")
    if diag.get("audience") == "shared":
        dropped_entries = int(diag.get("dropped_by_shared") or 0)
        dropped_facts = int(diag.get("facts_dropped_by_shared") or 0)
        if dropped_entries:
            notes.append(
                f"サーバーチャンネルでは公開可能なソース（GitHub / Inbox / Notion）のみ対象のため、"
                f"個人チャット等の記録 {dropped_entries}件 が除外されました（全記録は DM で確認できます）。"
            )
        elif dropped_facts:
            notes.append(
                f"サーバーチャンネルでは公開可能な項目（完了・進行・次の予定）のみ対象のため、"
                f"抽出した項目 {dropped_facts}件 が除外されました。"
            )
    source_errors = diag.get("source_errors") or {}
    if source_errors:
        err_text = ", ".join(f"{k}: {v}" for k, v in sorted(source_errors.items()))
        notes.append(f"取得に失敗したソース: {err_text}")
    if digest.get("status") == "degraded":
        if not diag.get("llm_configured", True):
            notes.append("DeepSeek API キーが未設定のため要約を実行できませんでした。")
        llm_errors = diag.get("llm_errors") or {}
        if llm_errors:
            err_text = ", ".join(f"{k}: {v}" for k, v in sorted(llm_errors.items()))
            notes.append(f"要約ステップのエラー: {err_text}")
    return notes


def _describe(row) -> str:
    when = f"{row['hour']:02d}:{row['minute']:02d}"
    which = "前日" if row["day_offset"] == 1 else "当日"
    state = "" if row["enabled"] else "（停止中）"
    return f"<#{row['channel_id']}> 毎日 {when}（{row['timezone']}）に{which}の進捗{state}"


# ---------------------------------------------------------------- scheduling


def due_subscriptions(now: datetime | None = None) -> list[tuple[dict, str]]:
    """Return (subscription, target_day) pairs whose time has come and that have no post yet."""
    ensure_schema()
    current = now or datetime.now(timezone.utc)
    with db.get_connection() as conn:
        subs = [dict(r) for r in conn.execute("SELECT * FROM discord_digest_subscriptions WHERE enabled=1")]
        due = []
        for sub in subs:
            try:
                tz = ZoneInfo(sub["timezone"])
            except (ZoneInfoNotFoundError, ValueError):
                continue
            local = current.astimezone(tz)
            scheduled = local.replace(hour=sub["hour"], minute=sub["minute"], second=0, microsecond=0)
            created = datetime.fromisoformat(sub["created_at"]).astimezone(tz)
            # Not before the time, not hours late (PC was off), and not for a slot that passed
            # before the subscription existed (registering at 15:00 does not post 10:00's at once).
            if not (scheduled <= local < scheduled + CATCHUP) or scheduled < created:
                continue
            day = (scheduled.date() - timedelta(days=sub["day_offset"])).isoformat()
            if conn.execute("SELECT 1 FROM discord_digest_posts WHERE subscription_id=? AND day=?",
                            (sub["id"], day)).fetchone():
                continue
            due.append((sub, day))
    return due


def run_due(now: datetime | None = None) -> int:
    queued = 0
    for sub, day in due_subscriptions(now):
        try:
            digest = life_log.generate(day, audience=audience_for(sub["guild_id"]))
        except Exception as exc:  # noqa: BLE001 - one bad day must not stop the loop
            log.warning("digest generation failed: %s", type(exc).__name__)
            digest = {"status": "failed", "text": "", "error": type(exc).__name__}
        # Only a real summary is posted. Anything else is recorded as failed, with the reason,
        # and never reaches the channel (a wrong report is worse than a missing one).
        ok = digest["status"] == "ok"
        error = None if ok else _failure_reason(digest)
        with db.get_connection() as conn:
            inserted = conn.execute(
                "INSERT OR IGNORE INTO discord_digest_posts(subscription_id,day,status,title,body,error,created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (sub["id"], day, "ready" if ok else "failed", f"{day} の進捗", digest["text"] if ok else "", error,
                 db.now_iso())).rowcount
        queued += inserted if ok else 0
    return queued


class DigestScheduler:
    def __init__(self, poll_seconds: float = 60.0) -> None:
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        ensure_schema()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="petit-discord-digest", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.wait(self.poll_seconds):
            try:
                if run_due():
                    log.info("Discord digest queued")
            except Exception as exc:  # noqa: BLE001
                log.warning("Discord digest tick failed: %s", type(exc).__name__)


_scheduler: DigestScheduler | None = None


def enabled() -> bool:
    return os.getenv("PETIT_DISCORD_DIGEST_ENABLED", "1").strip().lower() not in {"0", "false", "off", "no"}


def get_scheduler() -> DigestScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = DigestScheduler()
    return _scheduler


# ---------------------------------------------------------------- API (Bot -> Core)


class DigestCommand(BaseModel):
    action: str = Field(pattern=r"^(here|register|off|unregister|list|preview|review)$")
    author_id: str = Field(min_length=1, max_length=40, pattern=r"^[0-9]+$")
    guild_id: str | None = Field(default=None, max_length=40, pattern=r"^[0-9]+$")
    channel_id: str | None = Field(default=None, max_length=40, pattern=r"^[0-9]+$")
    time: str = Field(default="10:00", max_length=8)
    day: str = Field(default="yesterday", pattern=r"^(yesterday|today)$")
    timezone: str = Field(default="", max_length=64)


@router.post("/api/channels/discord/digests/command")
def command(body: DigestCommand, authorization: str | None = Header(default=None)) -> dict:
    discord_api._authorize(authorization)  # noqa: SLF001 - same service token as the Discord adapter
    _require_owner(body.author_id, body.guild_id)
    ensure_schema()
    if body.action == "list":
        with db.get_connection() as conn:
            rows = conn.execute("SELECT * FROM discord_digest_subscriptions ORDER BY id").fetchall()
        if not rows:
            return {"reply": "進捗投稿の登録はまだありません。投稿したい場所で `/petit digest action:register` を実行してください。"}
        lines = []
        with db.get_connection() as conn:
            for row in rows:
                lines.append("- " + _describe(row))
                bad = conn.execute("SELECT day, error FROM discord_digest_posts WHERE subscription_id=? AND status='failed' "
                                   "ORDER BY id DESC LIMIT 1", (row["id"],)).fetchone()
                if bad:
                    lines.append(f"  直近の失敗: {bad['day']}（{bad['error'] or '不明'}）")
        return {"reply": "進捗投稿の登録:\n" + "\n".join(lines)}
    if body.action in {"preview", "review"}:
        try:
            digest = life_log.generate(body.day, audience=audience_for(body.guild_id))
        except Exception as exc:  # noqa: BLE001
            log.exception("digest preview failed")
            return {
                "reply": f"⚠️ プレビューの生成中にエラーが発生しました（{type(exc).__name__}）。",
                "status": "failed",
                "warnings": [],
            }
        reply = digest["text"]
        if digest["status"] != "ok":
            reply += f"\n\n⚠️ この内容は定時投稿されません（{_failure_reason(digest)}）。"
            diag_notes = _preview_diagnostics(digest)
            if diag_notes:
                reply += "\n\n**診断情報**\n" + "\n".join("- " + note for note in diag_notes)
        warnings = digest.get("warnings") or []
        if warnings:
            # Preview is ephemeral, so file names can be shown; scheduled posts never include them.
            reply += "\n\n⚠️ **取り込みの注意**\n" + "\n".join("- " + note for note in warnings)
        return {"reply": reply, "status": digest["status"], "warnings": warnings}
    if not body.channel_id:
        raise HTTPException(400, "投稿先のチャンネルが分かりませんでした。")
    now = db.now_iso()
    if body.action in {"off", "unregister"}:
        with db.get_connection() as conn:
            changed = conn.execute("UPDATE discord_digest_subscriptions SET enabled=0, updated_at=? WHERE channel_id=?",
                                   (now, body.channel_id)).rowcount
            # Unsent posts must not go out later if the channel is registered again.
            conn.execute("UPDATE discord_digest_posts SET status='failed', error='登録解除' WHERE status='ready' AND "
                         "subscription_id IN (SELECT id FROM discord_digest_subscriptions WHERE channel_id=?)",
                         (body.channel_id,))
        return {"reply": f"<#{body.channel_id}> への進捗投稿を止めました。" if changed else "この場所には登録がありません。"}
    hour, minute = _parse_time(body.time)
    tz_name = body.timezone.strip() or life_log.timezone_name()
    _zone(tz_name)
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO discord_digest_subscriptions(channel_id,guild_id,hour,minute,timezone,day_offset,enabled,"
            "created_at,updated_at) VALUES(?,?,?,?,?,?,1,?,?) ON CONFLICT(channel_id) DO UPDATE SET "
            "guild_id=excluded.guild_id, hour=excluded.hour, minute=excluded.minute, timezone=excluded.timezone, "
            "day_offset=excluded.day_offset, enabled=1, created_at=excluded.created_at, updated_at=excluded.updated_at",
            (body.channel_id, body.guild_id, hour, minute, tz_name, DAY_OFFSETS[body.day], now, now))
        row = conn.execute("SELECT * FROM discord_digest_subscriptions WHERE channel_id=?", (body.channel_id,)).fetchone()
    return {"reply": "登録しました: " + _describe(row) + "\nすぐに中身を見たいときは `/petit digest action:preview`。"}


@router.get("/api/channels/discord/digests")
def claim(limit: int = Query(default=5, ge=1, le=20), authorization: str | None = Header(default=None)) -> dict:
    discord_api._authorize(authorization)  # noqa: SLF001
    ensure_schema()
    claimed = []
    with db.write_transaction() as conn:
        rows = conn.execute(
            "SELECT p.id, p.title, p.body, s.channel_id FROM discord_digest_posts p "
            "JOIN discord_digest_subscriptions s ON s.id=p.subscription_id "
            "WHERE p.status='ready' AND s.enabled=1 ORDER BY p.id LIMIT ?", (limit,)).fetchall()
        for row in rows:
            conn.execute("UPDATE discord_digest_posts SET status='claimed', claimed_at=? WHERE id=?", (db.now_iso(), row["id"]))
            claimed.append({"post_id": row["id"], "channel_id": row["channel_id"], "title": row["title"], "body": row["body"]})
    return {"posts": claimed}


class DigestReport(BaseModel):
    status: str = Field(pattern=r"^(sent|failed)$")
    error: str | None = Field(default=None, max_length=500)


@router.post("/api/channels/discord/digests/{post_id}")
def report(post_id: int, body: DigestReport, authorization: str | None = Header(default=None)) -> dict:
    discord_api._authorize(authorization)  # noqa: SLF001
    with db.get_connection() as conn:
        updated = conn.execute(
            "UPDATE discord_digest_posts SET status=?, error=?, sent_at=? WHERE id=? AND status='claimed'",
            (body.status, body.error, db.now_iso() if body.status == "sent" else None, post_id)).rowcount
    if not updated:
        raise HTTPException(404, "確保済みの投稿がありません。")
    return {"post_id": post_id, "status": body.status}
