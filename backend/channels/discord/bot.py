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
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
from typing import Any

import httpx

from ...discord_archive import extract_attachment_text
from .relay import (
    Incoming,
    approval_text,
    button_id,
    extract,
    notification_text,
    parse_button,
    parse_slash,
    payload,
    split,
)

log = logging.getLogger("petit.discord")
TIMEOUT = httpx.Timeout(connect=10, read=600, write=30, pool=10)
UNAVAILABLE = "いま PETIT 本体に繋がりません。PC が起動しているか確認してください。"

TEXT_EXTENSIONS = {".txt", ".md", ".pdf", ".json", ".csv", ".py", ".sh", ".log", ".tsv"}
MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024  # 10MB


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

    async def close(self) -> None:
        await self._client.aclose()


class ArchiveBuffer:
    """Non-blocking queue that relays archive events to Core with exponential backoff on outage."""

    def __init__(self, core: CoreClient, maxsize: int = 2000):
        self.core = core
        self.queue: asyncio.Queue[tuple[str, dict]] = asyncio.Queue(maxsize=maxsize)
        self._worker_task: asyncio.Task | None = None
        self._current_item: tuple[str, dict] | None = None

    @property
    def pending_count(self) -> int:
        return self.queue.qsize() + (1 if self._current_item is not None else 0)

    def push(self, event_type: str, data: dict) -> None:
        try:
            self.queue.put_nowait((event_type, data))
        except asyncio.QueueFull:
            log.warning("archive queue full; dropping event to maintain system stability")

    async def start(self) -> None:
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
            event_type, data = item
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
                self._current_item = None
                self.queue.task_done()
                backoff = 1.0
            else:
                log.info("Core temporarily unavailable for archive; retry in %.1fs (pending: %d)", backoff, self.pending_count)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 15.0)
                # Re-queue for delivery once Core recovers
                self._current_item = None
                await self.queue.put((event_type, data))
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
) -> str | None:
    """Relay a `/petit` slash command to Core and return the reply text."""
    parsed = parse_slash(data)
    if parsed is None:
        return None
    if not guild_id:
        return "このコマンドはサーバー内でのみ使えます。"
    sub, params = parsed

    if sub == "archive":
        action = str(params.get("action") or "list")
        if action == "list":
            allow_data = await core.archive_allowlist(guild_id=guild_id)
            allowed = allow_data.get("allow_guilds", {}).get(guild_id, {}).get("channels", [])
            if not allowed:
                return "このサーバーには保存対象として登録されたチャンネルはありません。"
            mentions = " ".join(f"<#{c}>" for c in allowed)
            return f"保存対象チャンネル（{len(allowed)}件）:\n{mentions}"
        elif action in {"register", "unregister"}:
            has_perm = manage_guild or bool(permissions and (permissions & 0x20))
            if not has_perm:
                return "保存対象の変更にはサーバーの管理権限（Manage Server）が必要です。"
            channel_id = params.get("channel")
            channel_ids = [str(channel_id)] if channel_id else []
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

    async def handle_archive_message(message) -> None:
        if not os.environ.get("PETIT_DISCORD_ARCHIVE_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}:
            return
        if getattr(message.author, "bot", False) or not message.guild:
            return

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
                    extracted = await asyncio.to_thread(extract_attachment_text, data, fn)
                except Exception as exc:
                    log.warning("failed to read attachment %s (%s)", fn, type(exc).__name__)

            norm_att.append({
                "attachment_id": str(getattr(a, "id", "")),
                "filename": fn,
                "content_type": ct,
                "size": sz,
                "url": str(getattr(a, "url", "") or ""),
                "extracted_text": extracted,
            })

        created_at_val = message.created_at.astimezone(timezone.utc).isoformat()
        edited_at_val = message.edited_at.astimezone(timezone.utc).isoformat() if message.edited_at else None
        parent_id = getattr(message.channel, "parent_id", None)

        is_priv = False
        if hasattr(message.channel, "is_private"):
            try:
                is_priv = bool(message.channel.is_private())
            except Exception:
                pass
        if not is_priv and getattr(message.channel, "type", None):
            type_str = str(message.channel.type)
            if "private" in type_str.lower():
                is_priv = True

        dto = {
            "message_id": str(message.id),
            "guild_id": str(message.guild.id),
            "guild_name": str(getattr(message.guild, "name", "") or ""),
            "channel_id": str(parent_id or message.channel.id),
            "channel_name": str(getattr(message.channel, "name", "") or ""),
            "thread_id": str(message.channel.id) if parent_id else None,
            "thread_name": str(getattr(message.channel, "name", "") or "") if parent_id else None,
            "is_private_thread": is_priv,
            "author_id": str(message.author.id),
            "author_name": str(getattr(message.author, "display_name", "") or getattr(message.author, "name", "")),
            "author_is_bot": bool(message.author.bot),
            "content": str(message.content or ""),
            "created_at": created_at_val,
            "edited_at": edited_at_val,
            "reply_to_message_id": str(message.reference.message_id) if getattr(message, "reference", None) and message.reference.message_id else None,
            "attachments": norm_att,
        }
        archive_buffer.push("event", dto)

    class PetitClient(discord.Client):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.tree = app_commands.CommandTree(self)

        async def setup_hook(self):
            try:
                await self.tree.sync()
            except Exception as exc:  # noqa: BLE001 - command sync failure must not crash Bot
                log.warning("command tree sync failed: %s", type(exc).__name__)
            await archive_buffer.start()
            self.loop.create_task(self.notification_loop())

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

    @petit_group.command(name="archive", description="このサーバーのDiscordログ保存対象を設定・確認します（管理者のみ）")
    async def _cmd_archive(interaction: discord.Interaction, action: str = "list",
                           scope: str = "channel", channel: discord.TextChannel | None = None):
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
            data = await core.relay(payload(incoming, text))
        await send_result(message.channel, data, first=lambda chunk: message.reply(chunk, mention_author=False))

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


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    service = os.environ.get("PETIT_DISCORD_SERVICE_TOKEN", "")
    if not token or len(service) < 32:
        raise SystemExit("DISCORD_BOT_TOKEN と PETIT_DISCORD_SERVICE_TOKEN（32文字以上）を設定してください。")
    core = CoreClient(os.environ.get("PETIT_CORE_URL", "http://127.0.0.1:8000"), service)
    build_client(core).run(token, log_handler=None)
