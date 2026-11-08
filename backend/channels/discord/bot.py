"""Discord Gateway client. Outbound connection only; Core is never exposed.

Environment:
  DISCORD_BOT_TOKEN            Bot token (Discord Developer Portal)
  PETIT_CORE_URL               e.g. http://127.0.0.1:8000
  PETIT_DISCORD_SERVICE_TOKEN  shared with Core (32+ chars)
"""
from __future__ import annotations

import asyncio
import logging
import os

import httpx

from .relay import Incoming, extract, payload, split

log = logging.getLogger("petit.discord")
TIMEOUT = httpx.Timeout(connect=10, read=600, write=30, pool=10)
UNAVAILABLE = "いま PETIT 本体に繋がりません。PC が起動しているか確認してください。"


class CoreClient:
    def __init__(self, base_url: str, token: str, transport: httpx.AsyncBaseTransport | None = None):
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=TIMEOUT, transport=transport,
                                         headers={"Authorization": "Bearer " + token})

    async def relay(self, body: dict) -> str:
        try:
            response = await self._client.post("/api/channels/discord/events", json=body)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("core relay failed: %s", type(exc).__name__)
            return UNAVAILABLE
        return str(data.get("reply") or "")

    async def close(self) -> None:
        await self._client.aclose()


def build_client(core: CoreClient):
    import discord  # optional dependency: requirements-discord.txt

    intents = discord.Intents.default()  # no privileged Message Content Intent
    intents.dm_messages = True
    client = discord.Client(intents=intents, allowed_mentions=discord.AllowedMentions.none())

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
            reply = await core.relay(payload(incoming, text))
        chunks = split(reply)
        for index, chunk in enumerate(chunks):
            if index == 0:
                await message.reply(chunk, mention_author=False)
            else:
                await message.channel.send(chunk)

    return client


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    service = os.environ.get("PETIT_DISCORD_SERVICE_TOKEN", "")
    if not token or len(service) < 32:
        raise SystemExit("DISCORD_BOT_TOKEN と PETIT_DISCORD_SERVICE_TOKEN（32文字以上）を設定してください。")
    core = CoreClient(os.environ.get("PETIT_CORE_URL", "http://127.0.0.1:8000"), service)
    client = build_client(core)
    try:
        client.run(token, log_handler=None)
    finally:
        asyncio.run(core.close())
