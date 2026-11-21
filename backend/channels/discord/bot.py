"""Discord Gateway client. Outbound connection only; Core is never exposed.

Environment:
  DISCORD_BOT_TOKEN            Bot token (Discord Developer Portal)
  PETIT_CORE_URL               e.g. http://127.0.0.1:8000
  PETIT_DISCORD_SERVICE_TOKEN  shared with Core (32+ chars)
  PETIT_DISCORD_POLL_SECONDS   notification poll interval (default 30)
  PETIT_DISCORD_ARCHIVE_ENABLED enable message archiving (default 1)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
from typing import Any

import httpx

from ...discord_archive import extract_attachment_text
from .relay import (
    RECENT_HISTORY_LIMIT,
    ContextMessage,
    Incoming,
    approval_text,
    button_id,
    extract,
    format_channel_context,
    notification_text,
    parse_button,
    parse_slash,
    payload,
    reminder_text,
    split,
)

log = logging.getLogger("petit.discord")
TIMEOUT = httpx.Timeout(connect=10, read=600, write=30, pool=10)
UNAVAILABLE = "いま PETIT 本体に繋がりません。PC が起動しているか確認してください。"

TEXT_EXTENSIONS = {".txt", ".md", ".pdf", ".json", ".csv", ".py", ".sh", ".log", ".tsv"}
MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024  # 10MB


def _to_context_message(msg: Any) -> ContextMessage | None:
    author = getattr(msg, "author", None)
    if author is None:
        return None
    content = (getattr(msg, "content", None) or "").strip()
    if not content:
        attachments = getattr(msg, "attachments", None) or []
        names = [getattr(att, "filename", "") for att in attachments if getattr(att, "filename", "")]
        if names:
            content = "[添付: " + ", ".join(names[:3]) + "]"
    if not content:
        return None
    author_name = str(getattr(author, "display_name", None) or getattr(author, "name", None) or "")
    return ContextMessage(
        author_name=author_name,
        content=content,
        is_bot=bool(getattr(author, "bot", False)),
        message_id=str(getattr(msg, "id", "") or ""),
    )


async def fetch_channel_context(message: Any, *, limit: int = RECENT_HISTORY_LIMIT) -> str:
    """Fetch recent channel messages and reply target for conversational context."""
    reply_to: ContextMessage | None = None
    ref = getattr(message, "reference", None)
    if ref is not None:
        resolved = getattr(ref, "resolved", None)
        if resolved is not None and hasattr(resolved, "content") and hasattr(resolved, "author"):
            reply_to = _to_context_message(resolved)
        elif getattr(ref, "message_id", None) and hasattr(message.channel, "fetch_message"):
            try:
                fetched = await message.channel.fetch_message(ref.message_id)
                reply_to = _to_context_message(fetched)
            except Exception as exc:
                log.debug("failed to fetch referenced message: %s", type(exc).__name__)

    recent: list[ContextMessage] = []
    if hasattr(message.channel, "history"):
        try:
            items: list[ContextMessage] = []
            async for hist_msg in message.channel.history(limit=limit, before=message):
                ctx_msg = _to_context_message(hist_msg)
                if ctx_msg is not None:
                    items.append(ctx_msg)
            recent = list(reversed(items))
        except Exception as exc:
            log.debug("failed to fetch channel history: %s", type(exc).__name__)

    return format_channel_context(recent, reply_to)


class CoreClient:
    def __init__(self, base_url: str, token: str, transport: httpx.AsyncBaseTransport | None = None):
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=TIMEOUT,
            transport=transport,
            headers={"Authorization": "Bearer " + token},
        )

    async def _call(self, method: str, path: str, **kwargs) -> dict | None:
        try:
            response = await self._client.request(method, path, **kwargs)
            if response.status_code in {400, 403, 404, 409, 429}:
                detail = response.json().get("detail")
                return {"reply": detail if isinstance(detail, str) else "この操作はできませんでした。", "approvals": []}
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("core %s %s failed: %s", method, path, type(exc).__name__)
            return None

    async def relay(self, body: dict) -> dict:
        return await self._call("POST", "/api/channels/discord/events", json=body) or {"reply": UNAVAILABLE, "approvals": []}

    async def decide(self, body: dict) -> dict:
        return await self._call("POST", "/api/channels/discord/approvals", json=body) or {"reply": UNAVAILABLE, "approvals": []}

    async def guild_command(self, subcommand: str, body: dict) -> dict:
        return await self._call("POST", f"/api/guild/{subcommand}", json=body) or {"reply": UNAVAILABLE, "approvals": []}

    async def claim_notifications(self) -> dict:
        return await self._call("GET", "/api/channels/discord/notifications") or {"notifications": []}

    async def report(self, event_id: int, status: str, error: str | None = None) -> None:
        await self._call("POST", f"/api/channels/discord/notifications/{event_id}", json={"status": status, "error": error})

    async def archive_event(self, body: dict) -> dict:
        return await self._call("POST", "/api/channels/discord/archive/events", json=body) or {}

    async def archive_delete(self, body: dict) -> dict:
        return await self._call("POST", "/api/channels/discord/archive/delete", json=body) or {}

    async def archive_register(self, body: dict) -> dict:
        return await self._call("POST", "/api/channels/discord/archive/register", json=body) or {}

    async def archive_allowlist(self, guild_id: str | None = None, zone: str | None = None) -> dict:
        params = {}
        if guild_id:
            params["guild_id"] = str(guild_id)
        if zone:
            params["zone"] = str(zone)
        return await self._call("GET", "/api/channels/discord/archive/allowlist", params=params) or {}

    async def archive_events_batch(self, events: list[dict]) -> dict:
        return await self._call("POST", "/api/channels/discord/archive/events/batch", json={"events": events}) or {}

    async def archive_checkpoints(self, guild_id: str | None = None) -> dict:
        params = {"guild_id": str(guild_id)} if guild_id else {}
        return await self._call("GET", "/api/channels/discord/archive/checkpoints", params=params) or {}

    async def archive_set_checkpoint(self, body: dict) -> dict:
        return await self._call("POST", "/api/channels/discord/archive/checkpoints", json=body) or {}

    async def archive_sync_config(self, guild_id: str | None = None) -> dict:
        params = {"guild_id": str(guild_id)} if guild_id else {}
        return await self._call("GET", "/api/channels/discord/archive/sync-config", params=params) or {}

    async def archive_set_sync_config(self, body: dict) -> dict:
        return await self._call("POST", "/api/channels/discord/archive/sync-config", json=body) or {}

    async def digest_command(self, body: dict) -> dict:
        return await self._call("POST", "/api/channels/discord/digests/command", json=body) or {"reply": UNAVAILABLE}

    async def claim_digests(self) -> dict:
        return await self._call("GET", "/api/channels/discord/digests") or {"posts": []}

    async def report_digest(self, post_id: int, status: str, error: str | None = None) -> None:
        await self._call("POST", f"/api/channels/discord/digests/{post_id}", json={"status": status, "error": error})

    async def claim_reminders(self) -> dict:
        return await self._call("GET", "/api/channels/discord/reminders") or {"reminders": []}

    async def report_reminder(
        self,
        scope: str,
        reminder_id: int,
        status: str,
        error: str | None = None,
        guild_id: str | None = None,
    ) -> None:
        body: dict[str, Any] = {"status": status, "error": error}
        if guild_id:
            body["guild_id"] = str(guild_id)
        await self._call("POST", f"/api/channels/discord/reminders/{scope}/{reminder_id}", json=body)

    async def admin_command(self, body: dict) -> dict:
        return await self._call("POST", "/api/channels/discord/admins", json=body) or {"reply": UNAVAILABLE}

    async def close(self) -> None:
        await self._client.aclose()


class ArchiveBuffer:
    """Persistent queue that relays archive events to Core with exponential backoff and recovery on restart."""

    def __init__(self, core: CoreClient, db_path: Path | str | None = None, maxsize: int = 2000):
        self.core = core
        self.maxsize = maxsize
        self.db_path = Path(db_path) if db_path and str(db_path) != ":memory:" else db_path
        if self.db_path is None:
            buf_env = os.environ.get("PETIT_ARCHIVE_BUFFER_DB")
            if buf_env:
                self.db_path = Path(buf_env) if buf_env != ":memory:" else ":memory:"
            else:
                self.db_path = Path(os.environ.get("PETIT_ARCHIVE_DIR", "storage/archive")) / "buffer_queue.sqlite"
        if isinstance(self.db_path, Path):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_db()
        self.queue: asyncio.Queue[tuple[int, str, dict]] = asyncio.Queue(maxsize=maxsize)
        self._worker_task: asyncio.Task | None = None
        self._current_item: tuple[int, str, dict] | None = None

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path), timeout=10.0)

    def _init_db(self) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS pending_archive_queue (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_type TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    """
                )
                conn.commit()
        except Exception as exc:
            log.warning("failed to init archive buffer db: %s", exc)

    @property
    def pending_count(self) -> int:
        try:
            with self._connect() as conn:
                row = conn.execute("SELECT COUNT(*) FROM pending_archive_queue").fetchone()
                return int(row[0]) if row else 0
        except Exception:
            return self.queue.qsize() + (1 if self._current_item is not None else 0)

    def push(self, event_type: str, data: dict) -> None:
        row_id = 0
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            payload_str = json.dumps(data)
            with self._connect() as conn:
                cur = conn.execute(
                    "INSERT INTO pending_archive_queue (event_type, payload_json, created_at) VALUES (?, ?, ?)",
                    (event_type, payload_str, now_iso),
                )
                conn.commit()
                row_id = cur.lastrowid or 0
        except Exception as exc:
            log.warning("failed to persist archive event: %s", exc)

        try:
            self.queue.put_nowait((row_id, event_type, data))
        except asyncio.QueueFull:
            log.warning("archive in-memory queue full; event retained in SQLite buffer")

    async def start(self) -> None:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT id, event_type, payload_json FROM pending_archive_queue ORDER BY id ASC LIMIT ?",
                    (self.maxsize,),
                ).fetchall()
                loaded_ids = {item[0] for item in list(self.queue._queue)} if hasattr(self.queue, "_queue") else set()
                for row_id, event_type, payload_str in rows:
                    if row_id not in loaded_ids:
                        try:
                            data = json.loads(payload_str)
                            self.queue.put_nowait((row_id, event_type, data))
                        except (asyncio.QueueFull, json.JSONDecodeError):
                            break
        except Exception as exc:
            log.warning("failed to load pending archive events from SQLite: %s", exc)

        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker())

    async def stop(self) -> None:
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

    async def _worker(self) -> None:
        backoff = 1.0
        while True:
            item = await self.queue.get()
            self._current_item = item
            row_id, event_type, data = item
            success = False
            try:
                if event_type == "event":
                    resp = await self.core.archive_event(data)
                    success = (resp.get("status") == "ok")
                elif event_type == "delete":
                    resp = await self.core.archive_delete(data)
                    success = (resp.get("status") == "ok")
            except Exception as exc:
                log.warning("archive worker request failed: %s", exc)
                success = False

            if success:
                if row_id:
                    try:
                        with self._connect() as conn:
                            conn.execute("DELETE FROM pending_archive_queue WHERE id=?", (row_id,))
                            conn.commit()
                    except Exception as exc:
                        log.warning("failed to delete sent archive event %d: %s", row_id, exc)
                self._current_item = None
                self.queue.task_done()
                backoff = 1.0
            else:
                log.info("Core temporarily unavailable for archive; retry in %.1fs (pending: %d)", backoff, self.pending_count)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 15.0)
                # Re-queue for delivery once Core recovers
                self._current_item = None
                await self.queue.put((row_id, event_type, data))
                self.queue.task_done()


async def deliver_notifications(core: CoreClient, fetch_user) -> int:
    """One poll: send each claimed notification as a DM and report the outcome."""
    data = await core.claim_notifications()
    owner = data.get("owner_id")
    sent = 0
    for item in data.get("notifications") or []:
        try:
            user = await fetch_user(int(owner))
            await user.send(notification_text(item))
        except Exception as exc:  # noqa: BLE001 - report every failure to Core
            await core.report(item["event_id"], "failed", type(exc).__name__)
        else:
            await core.report(item["event_id"], "sent")
            sent += 1
    return sent


def is_forum(channel) -> bool:
    return str(getattr(channel, "type", "")) == "forum"


async def deliver_digests(core: CoreClient, get_channel) -> int:
    """One poll: post each queued daily digest and report the outcome to Core.

    A forum channel gets a new post per day; a text channel or thread gets plain messages.
    """
    data = await core.claim_digests()
    sent = 0
    for post in data.get("posts") or []:
        try:
            channel = await get_channel(int(post["channel_id"]))
            chunks = split(str(post.get("body") or "")) or [str(post.get("title") or "")]
            target = channel
            if is_forum(channel):
                created = await channel.create_thread(name=str(post.get("title") or "進捗")[:100], content=chunks[0])
                target, chunks = getattr(created, "thread", created), chunks[1:]
            for chunk in chunks:
                await target.send(chunk)
        except Exception as exc:  # noqa: BLE001 - report every failure to Core
            await core.report_digest(post["post_id"], "failed", type(exc).__name__)
        else:
            await core.report_digest(post["post_id"], "sent")
            sent += 1
    return sent


async def deliver_reminders(core: CoreClient, get_channel, *, allowed_mentions_for=None) -> int:
    """One poll: send each claimed Discord channel reminder with targeted mention and report."""
    data = await core.claim_reminders()
    sent = 0
    for item in data.get("reminders") or []:
        scope = str(item.get("scope") or "owner")
        reminder_id = int(item["reminder_id"])
        guild_id = item.get("guild_id")
        try:
            channel = await get_channel(int(item["channel_id"]))
            text = reminder_text(item)
            send_kwargs: dict[str, Any] = {}
            if allowed_mentions_for is not None:
                send_kwargs["allowed_mentions"] = allowed_mentions_for(item)
            if is_forum(channel):
                await channel.create_thread(name=str(item.get("title") or "リマインダー")[:100], content=text, **send_kwargs)
            else:
                await channel.send(text, **send_kwargs)
        except Exception as exc:  # noqa: BLE001 - report every failure to Core
            await core.report_reminder(scope, reminder_id, "failed", type(exc).__name__, guild_id=guild_id)
        else:
            await core.report_reminder(scope, reminder_id, "sent", guild_id=guild_id)
            sent += 1
    return sent


_SYNC_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def _is_private_thread(channel: Any) -> bool:
    if hasattr(channel, "is_private"):
        try:
            return bool(channel.is_private())
        except Exception:
            pass
    ch_type = getattr(channel, "type", None)
    return bool(ch_type and "private" in str(ch_type).lower())


def _is_readable_channel(channel: Any, bot_member: Any) -> bool:
    if bot_member is not None and hasattr(channel, "permissions_for"):
        try:
            perms = channel.permissions_for(bot_member)
            if not (getattr(perms, "view_channel", True) and getattr(perms, "read_message_history", True)):
                return False
        except Exception:
            pass
    return True


async def build_message_dto(
    message: Any,
    attachment_semaphore: asyncio.Semaphore | None = None,
) -> dict[str, Any]:
    norm_att = []
    for a in getattr(message, "attachments", []):
        fn = str(getattr(a, "filename", "") or "")
        sz = int(getattr(a, "size", 0) or 0)
        ct = str(getattr(a, "content_type", "") or "")
        extracted = None
        suffix = Path(fn).suffix.lower()
        if suffix in TEXT_EXTENSIONS and sz <= MAX_ATTACHMENT_SIZE and hasattr(a, "read"):
            try:
                data = await a.read()
                if attachment_semaphore is not None:
                    async with attachment_semaphore:
                        extracted = await asyncio.wait_for(
                            asyncio.to_thread(extract_attachment_text, data, fn),
                            timeout=10.0,
                        )
                else:
                    extracted = await asyncio.wait_for(
                        asyncio.to_thread(extract_attachment_text, data, fn),
                        timeout=10.0,
                    )
            except asyncio.TimeoutError:
                log.warning("attachment parsing timed out for %s (>10s); skipping text extraction", fn)
                extracted = None
            except Exception as exc:
                log.warning("failed to read/parse attachment %s (%s)", fn, type(exc).__name__)
                extracted = None

        norm_att.append({
            "attachment_id": str(getattr(a, "id", "")),
            "filename": fn,
            "content_type": ct,
            "size": sz,
            "url": str(getattr(a, "url", "") or ""),
            "extracted_text": extracted,
        })

    created_at = getattr(message, "created_at", None)
    created_at_val = (
        created_at.astimezone(timezone.utc).isoformat()
        if isinstance(created_at, datetime)
        else str(created_at or datetime.now(timezone.utc).isoformat())
    )
    edited_at = getattr(message, "edited_at", None)
    edited_at_val = edited_at.astimezone(timezone.utc).isoformat() if isinstance(edited_at, datetime) else None
    parent_id = getattr(message.channel, "parent_id", None)
    parent = getattr(message.channel, "parent", None)

    return {
        "message_id": str(message.id),
        "guild_id": str(message.guild.id),
        "guild_name": str(getattr(message.guild, "name", "") or ""),
        "channel_id": str(parent_id or message.channel.id),
        "channel_name": str(getattr(parent, "name", "") if parent_id and parent else getattr(message.channel, "name", "") or ""),
        "thread_id": str(message.channel.id) if parent_id else None,
        "thread_name": str(getattr(message.channel, "name", "") or "") if parent_id else None,
        "is_private_thread": _is_private_thread(message.channel),
        "author_id": str(message.author.id),
        "author_name": str(getattr(message.author, "display_name", "") or getattr(message.author, "name", "")),
        "author_is_bot": bool(getattr(message.author, "bot", False)),
        "content": str(getattr(message, "content", "") or ""),
        "created_at": created_at_val,
        "edited_at": edited_at_val,
        "reply_to_message_id": (
            str(message.reference.message_id)
            if getattr(message, "reference", None) and message.reference.message_id
            else None
        ),
        "attachments": norm_att,
    }


async def collect_guild_sync_targets(
    guild: Any,
    *,
    allowed_channel_ids: set[str] | None = None,
    target_channel_id: str | None = None,
    include_all_readable: bool = False,
) -> tuple[list[str], list[Any]]:
    """Return (register_channel_ids, sync_channels_and_threads) for a guild."""
    bot_member = getattr(guild, "me", None)
    base_channels: list[Any] = []
    seen_ids: set[str] = set()

    for ch in list(getattr(guild, "text_channels", [])) + list(getattr(guild, "forums", [])):
        cid = str(getattr(ch, "id", ""))
        if not cid or cid in seen_ids:
            continue
        if _is_readable_channel(ch, bot_member):
            seen_ids.add(cid)
            base_channels.append(ch)

    register_ids: list[str] = []
    sync_targets: list[Any] = []
    sync_seen: set[str] = set()

    def _add_sync_target(obj: Any) -> None:
        oid = str(getattr(obj, "id", ""))
        if oid and oid not in sync_seen:
            sync_seen.add(oid)
            sync_targets.append(obj)

    for ch in base_channels:
        cid = str(ch.id)
        if include_all_readable:
            register_ids.append(cid)
        is_allowed = include_all_readable or (allowed_channel_ids is not None and cid in allowed_channel_ids)
        if target_channel_id and cid != target_channel_id:
            continue
        if is_allowed and hasattr(ch, "history"):
            _add_sync_target(ch)

    # Active threads
    for th in list(getattr(guild, "threads", [])):
        tid = str(getattr(th, "id", ""))
        pid = str(getattr(th, "parent_id", "") or "")
        if _is_private_thread(th):
            if allowed_channel_ids and tid in allowed_channel_ids and (not target_channel_id or target_channel_id == tid):
                _add_sync_target(th)
            continue
        if not _is_readable_channel(th, bot_member):
            continue
        parent_allowed = include_all_readable or (allowed_channel_ids is not None and (pid in allowed_channel_ids or tid in allowed_channel_ids))
        if parent_allowed and (not target_channel_id or target_channel_id in {tid, pid}):
            _add_sync_target(th)

    # Archived public threads on permitted base channels
    for ch in base_channels:
        cid = str(ch.id)
        if not include_all_readable and (allowed_channel_ids is None or cid not in allowed_channel_ids):
            continue
        if target_channel_id and target_channel_id != cid:
            continue
        if not hasattr(ch, "archived_threads"):
            continue
        try:
            async for th in ch.archived_threads(limit=None):
                if not _is_private_thread(th) and _is_readable_channel(th, bot_member):
                    _add_sync_target(th)
        except Exception as exc:
            log.debug("failed to list archived threads for channel %s: %s", cid, type(exc).__name__)

    return register_ids, sync_targets


async def sync_guild_archive(
    core: CoreClient,
    guild: Any,
    *,
    target_channel_id: str | None = None,
    days: int = 0,
    register_all: bool = False,
    author_id: str | None = None,
    manage_guild: bool = False,
    permissions: int | None = None,
    attachment_semaphore: asyncio.Semaphore | None = None,
    batch_size: int = 50,
) -> dict[str, int]:
    """Scan guild channels/threads and upload history to Core in batches."""
    guild_id = str(guild.id)
    allowed_set: set[str] | None = None

    if register_all:
        reg_ids, targets = await collect_guild_sync_targets(
            guild,
            target_channel_id=target_channel_id,
            include_all_readable=True,
        )
        if reg_ids and author_id:
            await core.archive_register({
                "guild_id": guild_id,
                "author_id": author_id,
                "channel_ids": reg_ids,
                "enabled": True,
                "manage_guild": manage_guild,
                "permissions": permissions,
            })
    else:
        allow_data = await core.archive_allowlist(guild_id=guild_id)
        allowed = allow_data.get("allow_guilds", {}).get(guild_id, {}).get("channels", [])
        allowed_set = {str(c) for c in allowed}
        _, targets = await collect_guild_sync_targets(
            guild,
            allowed_channel_ids=allowed_set,
            target_channel_id=target_channel_id,
            include_all_readable=False,
        )

    cp_data = await core.archive_checkpoints(guild_id=guild_id)
    checkpoints: dict[str, str] = cp_data.get("checkpoints") or {}

    synced_channels = 0
    total_fetched = 0
    total_saved = 0
    error_count = 0

    for ch in targets:
        ch_id = str(ch.id)
        started = datetime.now(timezone.utc)
        after: datetime | None = None
        if days > 0:
            after = started - timedelta(days=days)
        elif ch_id in checkpoints:
            try:
                after = datetime.fromisoformat(checkpoints[ch_id].replace("Z", "+00:00")) - timedelta(seconds=1)
            except ValueError:
                after = None

        batch: list[dict[str, Any]] = []
        try:
            async for msg in ch.history(limit=None, after=after, before=started, oldest_first=True):
                if getattr(getattr(msg, "author", None), "bot", False):
                    continue
                dto = await build_message_dto(msg, attachment_semaphore=attachment_semaphore)
                batch.append(dto)
                total_fetched += 1
                if len(batch) >= batch_size:
                    res = await core.archive_events_batch(batch)
                    total_saved += int(res.get("saved") or 0)
                    batch.clear()
                    await asyncio.sleep(0.05)

            if batch:
                res = await core.archive_events_batch(batch)
                total_saved += int(res.get("saved") or 0)

            if days <= 0:
                await core.archive_set_checkpoint({
                    "guild_id": guild_id,
                    "channel_id": ch_id,
                    "completed_at": started.isoformat().replace("+00:00", "Z"),
                    "author_id": author_id,
                })
            synced_channels += 1
        except Exception as exc:
            error_count += 1
            log.warning("archive sync failed for channel %s in guild %s (%s)", ch_id, guild_id, type(exc).__name__)
        await asyncio.sleep(0.1)

    return {
        "channels": synced_channels,
        "fetched": total_fetched,
        "saved": total_saved,
        "errors": error_count,
    }


async def dispatch_slash_interaction(
    core: CoreClient,
    *,
    interaction_id: str,
    guild_id: str | None,
    author_id: str,
    display_name: str,
    manage_guild: bool,
    permissions: int | None,
    data: dict | None,
    channel_id: str | None = None,
    guild: Any = None,
    schedule_sync: Any = None,
) -> str | None:
    """Relay a `/petit` slash command to Core and return the reply text."""
    parsed = parse_slash(data)
    if parsed is None:
        return None
    if parsed[0] == "admin":
        params = parsed[1]
        target_user = params.get("user")
        body = {
            "action": str(params.get("action") or "list"),
            "actor_id": author_id,
            "target_user_id": str(target_user) if target_user else None,
        }
        result = await core.admin_command(body)
        return str(result.get("reply") or "")
    if parsed[0] == "digest":
        # Owner-only; Core checks the owner and the place. Works in DMs too.
        params = parsed[1]
        target = params.get("channel") or channel_id
        body = {"action": str(params.get("action") or "register"), "author_id": author_id, "guild_id": guild_id,
                "channel_id": str(target) if target else None, "time": str(params.get("time") or "10:00"),
                "day": str(params.get("day") or "yesterday")}
        result = await core.digest_command(body)
        return str(result.get("reply") or "")
    if not guild_id:
        return "このコマンドはサーバー内でのみ使えます。"
    sub, params = parsed

    if sub == "archive":
        action = str(params.get("action") or "list")
        if action == "list":
            allow_data = await core.archive_allowlist(guild_id=guild_id)
            allowed = allow_data.get("allow_guilds", {}).get(guild_id, {}).get("channels", [])
            sync_data = await core.archive_sync_config(guild_id=guild_id)
            cfg = sync_data.get("config") or {}
            sync_status = (
                f"有効（毎日 {cfg.get('sync_time', '05:00')}＋起動時）"
                if cfg.get("enabled")
                else "無効"
            )
            if not allowed:
                return (
                    "このサーバーには保存対象として登録されたチャンネルはありません。\n"
                    f"毎朝定期同期: {sync_status}\n"
                    "全チャンネル一括設定＋過去ログ取得は `/petit archive action:init` で実行できます。"
                )
            mentions = " ".join(f"<#{c}>" for c in allowed)
            return f"保存対象チャンネル（{len(allowed)}件）:\n{mentions}\n毎朝定期同期: {sync_status}"

        has_perm = manage_guild or bool(permissions and (permissions & 0x20))

        if action == "init":
            if not has_perm:
                return "初期セットアップ（全チャンネル一括登録）にはサーバーの管理権限（Manage Server）が必要です。"
            sync_time = str(params.get("time") or "05:00").strip()
            if not _SYNC_TIME_RE.fullmatch(sync_time):
                return "時刻は HH:MM（00:00〜23:59）の形式で指定してください。"
            res_cfg = await core.archive_set_sync_config({
                "guild_id": guild_id,
                "author_id": author_id,
                "enabled": True,
                "sync_time": sync_time,
                "manage_guild": manage_guild,
                "permissions": permissions,
            })
            if res_cfg.get("status") != "ok":
                return str(res_cfg.get("reply") or res_cfg.get("detail") or res_cfg.get("error") or "定期同期の設定に失敗しました。")

            if guild is not None and schedule_sync is not None:
                started = schedule_sync(
                    guild,
                    register_all=True,
                    author_id=author_id,
                    manage_guild=manage_guild,
                    permissions=permissions,
                )
                if not started:
                    return f"このサーバーでは現在スキャンを実行中です。毎朝 {sync_time} の定期同期は有効にしました。"
            return (
                "サーバー内の読み取り可能な全チャンネルを保存対象に登録し、過去ログの全スキャンをバックグラウンドで開始しました。\n"
                f"毎朝 {sync_time}（および Bot 起動時）の差分定期同期も有効になっています。"
            )

        if action == "schedule":
            if not has_perm:
                return "定期同期の設定変更にはサーバーの管理権限（Manage Server）が必要です。"
            enabled = bool(params.get("enabled", True))
            sync_time = str(params.get("time") or "05:00").strip()
            if not _SYNC_TIME_RE.fullmatch(sync_time):
                return "時刻は HH:MM（00:00〜23:59）の形式で指定してください。"
            res = await core.archive_set_sync_config({
                "guild_id": guild_id,
                "author_id": author_id,
                "enabled": enabled,
                "sync_time": sync_time,
                "manage_guild": manage_guild,
                "permissions": permissions,
            })
            if res.get("status") == "ok":
                state_str = f"有効（毎日 {sync_time}）" if enabled else "無効"
                return f"毎朝定期同期の設定を更新しました: {state_str}"
            return str(res.get("reply") or res.get("detail") or res.get("error") or "定期同期の設定更新に失敗しました。")

        if action in {"register", "unregister"}:
            if not has_perm:
                return "保存対象の変更にはサーバーの管理権限（Manage Server）が必要です。"
            target_ch_id = params.get("channel")
            channel_ids = [str(target_ch_id)] if target_ch_id else []
            enable = (action == "register")
            res = await core.archive_register({
                "guild_id": guild_id,
                "author_id": author_id,
                "channel_ids": channel_ids,
                "enabled": enable,
                "manage_guild": manage_guild,
                "permissions": permissions,
            })
            if res.get("status") == "ok":
                action_str = "登録" if enable else "解除"
                return f"チャンネルの保存対象{action_str}を更新しました（{len(channel_ids)}件）。"
            detail = res.get("reply") or res.get("error") or "保存設定の更新に失敗しました。"
            return str(detail)

        if action == "sync":
            if not has_perm:
                return "過去ログの差分同期にはサーバーの管理権限（Manage Server）が必要です。"
            target_ch_id = params.get("channel")
            days = max(0, int(params.get("days") or 0))
            target_str = f"<#{target_ch_id}>" if target_ch_id else "登録チャンネル全件"
            period_str = f"直近{days}日" if days > 0 else "全期間 / 前回チェックポイント以降"
            if guild is not None and schedule_sync is not None:
                started = schedule_sync(
                    guild,
                    target_channel_id=str(target_ch_id) if target_ch_id else None,
                    days=days,
                    author_id=author_id,
                    manage_guild=manage_guild,
                    permissions=permissions,
                )
                if not started:
                    return "このサーバーでは現在別の過去ログ同期が実行中です。完了後に再度お試しください。"
            return f"過去ログの同期をバックグラウンドで開始しました（対象: {target_str}、期間: {period_str}）。"

    body: dict = {
        "interaction_id": interaction_id,
        "guild_id": guild_id,
        "author_id": author_id,
    }
    if sub in {"setup", "reset"}:
        body["manage_guild"] = manage_guild
        body["permissions"] = permissions
        if sub == "setup":
            if "timezone" in params:
                body["timezone"] = str(params["timezone"])
            if "daily_call_limit" in params:
                body["daily_call_limit"] = int(params["daily_call_limit"])
            if "daily_token_limit" in params:
                body["daily_token_limit"] = int(params["daily_token_limit"])
            if "user_hourly_limit" in params:
                body["user_hourly_limit"] = int(params["user_hourly_limit"])
    elif sub == "me":
        body["display_name"] = str(params.get("display_name") or display_name or "")
        body["role_note"] = str(params.get("role_note") or "")
        body["memo"] = str(params.get("memo") or "")
    result = await core.guild_command(sub, body)
    return str(result.get("reply") or "")


def build_client(core: CoreClient):
    import discord  # optional dependency: requirements-discord.txt
    from discord import app_commands

    # Slash command parameters are string annotations (``from __future__ import annotations``);
    # discord.py evaluates them against this module's globals, so the lazily imported module
    # must be visible there or building the command tree raises NameError.
    globals().setdefault("discord", discord)

    intents = discord.Intents.default()
    intents.dm_messages = True
    try:
        intents.message_content = True
    except AttributeError:
        pass

    archive_buffer = ArchiveBuffer(core)

    def approval_view(item: dict):
        view = discord.ui.View(timeout=None)
        view.add_item(
            discord.ui.Button(
                label="承認する",
                style=discord.ButtonStyle.success,
                custom_id=button_id(item["approval_id"], True),
            )
        )
        view.add_item(
            discord.ui.Button(
                label="やめる",
                style=discord.ButtonStyle.secondary,
                custom_id=button_id(item["approval_id"], False),
            )
        )
        return view

    async def send_result(channel, data: dict, first=None) -> None:
        chunks = split(str(data.get("reply") or ""))
        for index, chunk in enumerate(chunks):
            if index == 0 and first is not None:
                await first(chunk)
            else:
                await channel.send(chunk)
        for item in data.get("approvals") or []:
            await channel.send(approval_text(item), view=approval_view(item))

    attachment_semaphore = asyncio.Semaphore(2)

    async def handle_archive_message(message) -> None:
        if not os.environ.get("PETIT_DISCORD_ARCHIVE_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}:
            return
        if getattr(message.author, "bot", False) or not message.guild:
            return
        dto = await build_message_dto(message, attachment_semaphore=attachment_semaphore)
        archive_buffer.push("event", dto)

    class PetitClient(discord.Client):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.tree = app_commands.CommandTree(self)
            self._sync_active: set[str] = set()
            self._last_daily_sync: dict[str, str] = {}

        def schedule_guild_sync(
            self,
            guild: Any,
            *,
            target_channel_id: str | None = None,
            days: int = 0,
            register_all: bool = False,
            author_id: str | None = None,
            manage_guild: bool = False,
            permissions: int | None = None,
        ) -> bool:
            gid = str(guild.id)
            if gid in self._sync_active:
                return False
            self._sync_active.add(gid)

            async def _runner() -> None:
                try:
                    summary = await sync_guild_archive(
                        core,
                        guild,
                        target_channel_id=target_channel_id,
                        days=days,
                        register_all=register_all,
                        author_id=author_id,
                        manage_guild=manage_guild,
                        permissions=permissions,
                        attachment_semaphore=attachment_semaphore,
                    )
                    log.info(
                        "archive sync finished for guild %s: channels=%d fetched=%d saved=%d errors=%d",
                        gid,
                        summary["channels"],
                        summary["fetched"],
                        summary["saved"],
                        summary["errors"],
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("archive sync task crashed for guild %s (%s)", gid, type(exc).__name__)
                finally:
                    self._sync_active.discard(gid)

            self.loop.create_task(_runner())
            return True

        async def setup_hook(self):
            try:
                await self.tree.sync()
            except Exception as exc:  # noqa: BLE001 - command sync failure must not crash Bot
                log.warning("command tree sync failed: %s", type(exc).__name__)
            await archive_buffer.start()
            self.loop.create_task(self.notification_loop())
            self.loop.create_task(self.digest_loop())
            self.loop.create_task(self.reminder_loop())
            self.loop.create_task(self.archive_sync_loop())

        async def close(self):
            await archive_buffer.stop()
            await super().close()

        async def notification_loop(self):
            await self.wait_until_ready()
            interval = max(10, int(os.environ.get("PETIT_DISCORD_POLL_SECONDS", "30") or 30))
            while not self.is_closed():
                try:
                    await deliver_notifications(core, self.fetch_user)
                except Exception as exc:  # noqa: BLE001 - keep polling
                    log.warning("notification poll failed: %s", type(exc).__name__)
                await asyncio.sleep(interval)

        async def resolve_channel(self, channel_id: int):
            return self.get_channel(channel_id) or await self.fetch_channel(channel_id)

        async def digest_loop(self):
            await self.wait_until_ready()
            interval = max(10, int(os.environ.get("PETIT_DISCORD_POLL_SECONDS", "30") or 30))
            while not self.is_closed():
                try:
                    await deliver_digests(core, self.resolve_channel)
                except Exception as exc:  # noqa: BLE001 - keep polling
                    log.warning("digest poll failed: %s", type(exc).__name__)
                await asyncio.sleep(interval)

        async def reminder_loop(self):
            await self.wait_until_ready()
            interval = max(5, int(os.environ.get("PETIT_DISCORD_REMINDER_POLL_SECONDS", "15") or 15))

            def _allowed_mentions(item: dict) -> discord.AllowedMentions:
                if item.get("mention_target") == "everyone":
                    return discord.AllowedMentions(everyone=True)
                author_id = str(item.get("author_id") or "")
                if author_id.isdigit():
                    return discord.AllowedMentions(users=[discord.Object(id=int(author_id))])
                return discord.AllowedMentions.none()

            while not self.is_closed():
                try:
                    await deliver_reminders(core, self.resolve_channel, allowed_mentions_for=_allowed_mentions)
                except Exception as exc:  # noqa: BLE001 - keep polling
                    log.warning("reminder poll failed: %s", type(exc).__name__)
                await asyncio.sleep(interval)

        async def archive_sync_loop(self):
            await self.wait_until_ready()
            startup_done = False
            while not self.is_closed():
                try:
                    if os.environ.get("PETIT_DISCORD_ARCHIVE_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}:
                        now_local = datetime.now()
                        today = now_local.strftime("%Y-%m-%d")
                        now_hhmm = now_local.strftime("%H:%M")
                        for guild in list(self.guilds):
                            gid = str(guild.id)
                            sync_data = await core.archive_sync_config(guild_id=gid)
                            cfg = sync_data.get("config") or {}
                            if not cfg.get("enabled"):
                                continue
                            sync_time = str(cfg.get("sync_time") or "05:00")
                            if not startup_done:
                                self.schedule_guild_sync(guild)
                                if now_hhmm >= sync_time:
                                    self._last_daily_sync[gid] = today
                            elif now_hhmm >= sync_time and self._last_daily_sync.get(gid) != today:
                                if self.schedule_guild_sync(guild):
                                    self._last_daily_sync[gid] = today
                        startup_done = True
                except Exception as exc:  # noqa: BLE001 - keep polling
                    log.warning("archive sync loop failed: %s", type(exc).__name__)
                await asyncio.sleep(60)

    client = PetitClient(intents=intents, allowed_mentions=discord.AllowedMentions.none())
    petit_group = app_commands.Group(name="petit", description="プティのサーバー設定・プロフィール管理")

    @petit_group.command(name="setup", description="このサーバーでプティの Guild モードを有効化します（管理者のみ）")
    async def _cmd_setup(interaction: discord.Interaction, timezone: str = "Asia/Tokyo",
                         daily_call_limit: int = 50, daily_token_limit: int = 60000):
        pass  # handled centrally in on_interaction

    @petit_group.command(name="reset", description="このサーバーのプティ設定と保存データを削除します（管理者のみ）")
    async def _cmd_reset(interaction: discord.Interaction):
        pass

    @petit_group.command(name="me", description="このサーバーでプティが覚えている自分の情報を確認・更新します")
    async def _cmd_me(interaction: discord.Interaction, display_name: str = "", role_note: str = "", memo: str = ""):
        pass

    @petit_group.command(name="forget-me", description="このサーバーに保存された自分の記録をすべて消去します")
    async def _cmd_forget_me(interaction: discord.Interaction):
        pass

    @petit_group.command(name="archive", description="Discord過去ログの一括取得・毎朝同期・保存対象を設定・確認します（管理者のみ）")
    @app_commands.describe(
        action="init=全チャンネル登録+全スキャン+毎朝同期 / sync=過去ログ同期 / register=追加 / unregister=除外 / list=確認 / schedule=定期同期設定",
        channel="対象チャンネル（register/unregister/sync で使用）",
        days="sync時の取得日数（0で前回続き/全期間）",
        time="毎朝同期する時刻（HH:MM、既定 05:00）",
        enabled="schedule時の定期同期 ON/OFF",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="init（全チャンネル初期セットアップ）", value="init"),
            app_commands.Choice(name="sync（今すぐ過去ログ同期）", value="sync"),
            app_commands.Choice(name="list（設定・対象一覧）", value="list"),
            app_commands.Choice(name="schedule（毎朝同期の時刻・ON/OFF）", value="schedule"),
            app_commands.Choice(name="register（チャンネル追加）", value="register"),
            app_commands.Choice(name="unregister（チャンネル除外）", value="unregister"),
        ]
    )
    async def _cmd_archive(
        interaction: discord.Interaction,
        action: str = "list",
        channel: discord.TextChannel | discord.ForumChannel | discord.Thread | None = None,
        days: int = 0,
        time: str = "05:00",
        enabled: bool = True,
    ):
        pass

    @petit_group.command(name="digest", description="毎日の進捗投稿を登録・停止・確認します（持ち主のみ）")
    @app_commands.describe(action="register=登録 / unregister=解除 / list=一覧 / preview=今すぐ自分だけに表示",
                           time="投稿する時刻（HH:MM）", day="まとめる日",
                           channel="投稿先（省略時はこの場所。フォーラムなら毎日新しい投稿を作ります）")
    @app_commands.choices(
        action=[app_commands.Choice(name=n, value=n) for n in ("register", "unregister", "list", "preview")],
        day=[app_commands.Choice(name="前日", value="yesterday"), app_commands.Choice(name="当日", value="today")])
    async def _cmd_digest(interaction: discord.Interaction, action: str = "register", time: str = "10:00",
                          day: str = "yesterday",
                          channel: discord.TextChannel | discord.ForumChannel | discord.Thread | None = None):
        pass

    @petit_group.command(name="admin", description="PETIT管理者の追加・解除・一覧確認を行います（初期管理者のみ）")
    @app_commands.describe(action="add=管理者に追加 / remove=管理者から解除 / list=一覧表示",
                           user="追加・解除するユーザー（メンションで選択）")
    @app_commands.choices(
        action=[app_commands.Choice(name=n, value=n) for n in ("add", "remove", "list")])
    async def _cmd_admin(interaction: discord.Interaction, action: str = "list",
                         user: discord.User | None = None):
        pass

    client.tree.add_command(petit_group)

    @client.event
    async def on_ready():
        log.info("connected as %s", client.user)

    @client.event
    async def on_message(message):
        if client.user is None:
            return

        # Background archival ingestion (never delays conversational reply)
        asyncio.create_task(handle_archive_message(message))

        incoming = Incoming(
            event_id=str(message.id),
            channel_id=str(message.channel.id),
            guild_id=str(message.guild.id) if message.guild else None,
            author_id=str(message.author.id),
            content=message.content or "",
            author_is_bot=bool(message.author.bot),
            mentions_bot=client.user in message.mentions,
            display_name=getattr(message.author, "display_name", "") or "",
        )
        text = extract(incoming, str(client.user.id))
        if text is None:
            return
        async with message.channel.typing():
            channel_context = await fetch_channel_context(message)
            data = await core.relay(payload(incoming, text, channel_context=channel_context))
        await send_result(message.channel, data, first=lambda chunk: message.reply(chunk, mention_author=False))

    @client.event
    async def on_message_edit(before, after):
        if client.user is None or not getattr(after, "guild", None):
            return
        # Background archival ingestion for edited messages (upserts revised content)
        asyncio.create_task(handle_archive_message(after))

    @client.event
    async def on_raw_message_delete(payload_del):
        if payload_del.guild_id is None:
            return
        archive_buffer.push("delete", {
            "message_id": str(payload_del.message_id),
            "guild_id": str(payload_del.guild_id),
            "channel_id": str(payload_del.channel_id),
        })

    @client.event
    async def on_raw_bulk_message_delete(payload_bulk):
        if payload_bulk.guild_id is None:
            return
        for mid in payload_bulk.message_ids:
            archive_buffer.push("delete", {
                "message_id": str(mid),
                "guild_id": str(payload_bulk.guild_id),
                "channel_id": str(payload_bulk.channel_id),
            })

    @client.event
    async def on_interaction(interaction):
        if interaction.type == discord.InteractionType.application_command:
            perms = getattr(interaction.user, "guild_permissions", None) or getattr(interaction, "permissions", None)
            manage_guild = bool(getattr(perms, "manage_guild", False))
            perm_value = getattr(perms, "value", None)
            await interaction.response.defer(ephemeral=True)
            reply = await dispatch_slash_interaction(
                core,
                interaction_id=str(interaction.id),
                guild_id=str(interaction.guild_id) if interaction.guild_id else None,
                author_id=str(interaction.user.id),
                display_name=getattr(interaction.user, "display_name", "") or "",
                manage_guild=manage_guild,
                permissions=perm_value if isinstance(perm_value, int) else None,
                data=interaction.data,
                channel_id=str(interaction.channel_id) if interaction.channel_id else None,
                guild=getattr(interaction, "guild", None),
                schedule_sync=client.schedule_guild_sync,
            )
            if reply:
                for chunk in split(reply):
                    await interaction.followup.send(chunk, ephemeral=True)
            return

        if interaction.type != discord.InteractionType.component:
            return
        parsed = parse_button((interaction.data or {}).get("custom_id"))
        if parsed is None:
            return
        approval_id, approved = parsed
        await interaction.response.defer()
        data = await core.decide({
            "interaction_id": str(interaction.id),
            "approval_id": approval_id,
            "guild_id": str(interaction.guild_id) if interaction.guild_id else None,
            "author_id": str(interaction.user.id),
            "approved": approved,
        })
        if interaction.message is not None and data.get("reply") != UNAVAILABLE:
            mark = "✅ 承認しました" if approved else "↩️ やめました"
            try:
                await interaction.message.edit(content=interaction.message.content + "\n" + mark, view=None)
            except discord.HTTPException:
                pass
        await send_result(interaction.channel, data)

    return client


def _configure_logging() -> None:
    log_dir = Path(__file__).resolve().parents[3] / "storage"
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_dir / "discord_bot.log", encoding="utf-8"))
    except OSError:
        pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        handlers=handlers,
    )


def main() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    _configure_logging()
    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    service = os.environ.get("PETIT_DISCORD_SERVICE_TOKEN", "")
    if not token or len(service) < 32:
        raise SystemExit("DISCORD_BOT_TOKEN と PETIT_DISCORD_SERVICE_TOKEN（32文字以上）を設定してください。")
    core = CoreClient(os.environ.get("PETIT_CORE_URL", "http://127.0.0.1:8000"), service)
    build_client(core).run(token, log_handler=None)
