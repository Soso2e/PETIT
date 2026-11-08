"""Discord Gateway client. Outbound connection only; Core is never exposed.

Environment:
  DISCORD_BOT_TOKEN            Bot token (Discord Developer Portal)
  PETIT_CORE_URL               e.g. http://127.0.0.1:8000
  PETIT_DISCORD_SERVICE_TOKEN  shared with Core (32+ chars)
  PETIT_DISCORD_POLL_SECONDS   notification poll interval (default 30)
"""
from __future__ import annotations

import asyncio
import logging
import os

import httpx

from .relay import (Incoming, approval_text, button_id, extract, notification_text, parse_button, payload, split)

log = logging.getLogger("petit.discord")
TIMEOUT = httpx.Timeout(connect=10, read=600, write=30, pool=10)
UNAVAILABLE = "いま PETIT 本体に繋がりません。PC が起動しているか確認してください。"


class CoreClient:
    def __init__(self, base_url: str, token: str, transport: httpx.AsyncBaseTransport | None = None):
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=TIMEOUT, transport=transport,
                                         headers={"Authorization": "Bearer " + token})

    async def _call(self, method: str, path: str, **kwargs) -> dict | None:
        try:
            response = await self._client.request(method, path, **kwargs)
            if response.status_code in {403, 404, 409, 429}:
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

    async def claim_notifications(self) -> dict:
        return await self._call("GET", "/api/channels/discord/notifications") or {"notifications": []}

    async def report(self, event_id: int, status: str, error: str | None = None) -> None:
        await self._call("POST", f"/api/channels/discord/notifications/{event_id}", json={"status": status, "error": error})

    async def close(self) -> None:
        await self._client.aclose()


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


def build_client(core: CoreClient):
    import discord  # optional dependency: requirements-discord.txt

    intents = discord.Intents.default()  # no privileged Message Content Intent
    intents.dm_messages = True

    def approval_view(item: dict):
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(label="承認する", style=discord.ButtonStyle.success,
                                        custom_id=button_id(item["approval_id"], True)))
        view.add_item(discord.ui.Button(label="やめる", style=discord.ButtonStyle.secondary,
                                        custom_id=button_id(item["approval_id"], False)))
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

    class PetitClient(discord.Client):
        async def setup_hook(self):
            self.loop.create_task(self.notification_loop())

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

    @client.event
    async def on_ready():
        log.info("connected as %s", client.user)

    @client.event
    async def on_message(message):
        if client.user is None:
            return
        incoming = Incoming(
            event_id=str(message.id), channel_id=str(message.channel.id),
            guild_id=str(message.guild.id) if message.guild else None, author_id=str(message.author.id),
            content=message.content or "", author_is_bot=bool(message.author.bot),
            mentions_bot=client.user in message.mentions)
        text = extract(incoming, str(client.user.id))
        if text is None:
            return
        async with message.channel.typing():
            data = await core.relay(payload(incoming, text))
        await send_result(message.channel, data, first=lambda chunk: message.reply(chunk, mention_author=False))

    @client.event
    async def on_interaction(interaction):
        if interaction.type != discord.InteractionType.component:
            return
        parsed = parse_button((interaction.data or {}).get("custom_id"))
        if parsed is None:
            return
        approval_id, approved = parsed
        await interaction.response.defer()
        data = await core.decide({"interaction_id": str(interaction.id), "approval_id": approval_id,
                                  "guild_id": str(interaction.guild_id) if interaction.guild_id else None,
                                  "author_id": str(interaction.user.id), "approved": approved})
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
