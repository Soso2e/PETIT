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
    display_name: str = ""


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
    body = {"event_id": incoming.event_id, "channel_id": incoming.channel_id, "guild_id": incoming.guild_id,
            "author_id": incoming.author_id, "message": text[:20000]}
    if incoming.display_name:
        body["display_name"] = incoming.display_name[:120]
    return body


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


BUTTON_PREFIX = "petit:"


def button_id(approval_id: str, approved: bool) -> str:
    return f"{BUTTON_PREFIX}{'approve' if approved else 'reject'}:{approval_id}"


def parse_button(custom_id: str | None) -> tuple[str, bool] | None:
    """Return (approval_id, approved) for PETIT buttons, else None."""
    if not custom_id or not custom_id.startswith(BUTTON_PREFIX):
        return None
    parts = custom_id.split(":")
    if len(parts) != 3 or parts[1] not in {"approve", "reject"} or not parts[2].isalnum():
        return None
    return parts[2], parts[1] == "approve"


def approval_text(item: dict) -> str:
    preview = str(item.get("preview") or "").replace("```", "'''")
    return f"**確認: {item.get('name', '')}**\n```\n{preview}\n```"[:LIMIT]


def notification_text(item: dict) -> str:
    return f"**{item.get('title', '')}**\n{item.get('body', '')}"[:LIMIT]


SLASH_SUBCOMMANDS = {"setup", "reset", "me", "forget-me"}


def parse_slash(data: dict | None) -> tuple[str, dict] | None:
    """Parse Discord application_command interaction data for `/petit <subcommand>`."""
    if not isinstance(data, dict) or data.get("name") != "petit":
        return None
    options = data.get("options") or []
    if not options or not isinstance(options[0], dict):
        return None
    sub = options[0].get("name")
    if sub not in SLASH_SUBCOMMANDS:
        return None
    params = {}
    for opt in options[0].get("options") or []:
        if isinstance(opt, dict) and "name" in opt and "value" in opt:
            params[str(opt["name"])] = opt["value"]
    return sub, params

