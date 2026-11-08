"""Pure relay logic for the Discord Bot: no Discord or network objects here."""
from __future__ import annotations

import re
from dataclasses import dataclass

LIMIT = 2000


@dataclass(frozen=True)
class Incoming:
    event_id: str
    channel_id: str
    guild_id: str | None
    author_id: str
    content: str
    author_is_bot: bool
    mentions_bot: bool


def extract(incoming: Incoming, bot_user_id: str) -> str | None:
    """Return the text to relay, or None when the Bot should stay silent.

    DMs are always handled; in guilds only explicit mentions are, so PETIT does
    not read channel traffic (and needs no Message Content Intent).
    """
    if incoming.author_is_bot:
        return None
    if incoming.guild_id is not None and not incoming.mentions_bot:
        return None
    text = re.sub(rf"<@!?{re.escape(bot_user_id)}>", "", incoming.content).strip()
    return text or None


def payload(incoming: Incoming, text: str) -> dict:
    return {"event_id": incoming.event_id, "channel_id": incoming.channel_id, "guild_id": incoming.guild_id,
            "author_id": incoming.author_id, "message": text[:20000]}


def split(text: str, limit: int = LIMIT) -> list[str]:
    """Split on paragraph, then line, then hard boundaries; never drops text."""
    text = text.strip()
    if not text:
        return []
    chunks: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n\n", 0, limit)
        if cut <= 0:
            cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip("\n")
    if text:
        chunks.append(text)
    return chunks
