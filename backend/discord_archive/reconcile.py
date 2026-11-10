"""Per-channel checkpoints and bounded backfill / reconciliation."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from .archive import DiscordArchive, utc_iso
from .ingest import ArchiveIngestor, extract_attachment_text
from .policy import ArchivePolicy

log = logging.getLogger("petit.discord_archive")


def message_to_dto(msg: Any, extract_attachments: bool = True) -> dict[str, Any]:
    channel = msg.channel
    parent_id = getattr(channel, "parent_id", None)
    parent = getattr(channel, "parent", None)
    author = msg.author
    guild = getattr(msg, "guild", None)

    is_priv = bool(getattr(channel, "is_private", lambda: False)())
    norm_attachments = []
    for a in getattr(msg, "attachments", []):
        att_id = str(getattr(a, "id", ""))
        fn = str(getattr(a, "filename", ""))
        ct = str(getattr(a, "content_type", "") or "")
        sz = int(getattr(a, "size", 0) or 0)
        url = str(getattr(a, "url", "") or "")
        norm_attachments.append(
            {
                "attachment_id": att_id,
                "filename": fn,
                "content_type": ct,
                "size": sz,
                "url": url,
            }
        )

    return {
        "message_id": str(msg.id),
        "guild_id": str(guild.id) if guild else "",
        "guild_name": getattr(guild, "name", "") if guild else "",
        "channel_id": str(parent_id or channel.id),
        "channel_name": getattr(parent, "name", "") if parent_id else getattr(channel, "name", ""),
        "thread_id": str(channel.id) if parent_id else None,
        "thread_name": getattr(channel, "name", "") if parent_id else None,
        "is_private_thread": is_priv,
        "author_id": str(author.id),
        "author_name": getattr(author, "display_name", "") or getattr(author, "name", ""),
        "author_is_bot": bool(getattr(author, "bot", False)),
        "content": str(getattr(msg, "content", "") or ""),
        "created_at": getattr(msg, "created_at", None),
        "edited_at": getattr(msg, "edited_at", None),
        "reply_to_message_id": str(msg.reference.message_id) if getattr(msg, "reference", None) and msg.reference.message_id else None,
        "attachments": norm_attachments,
    }


class ArchiveReconciler:
    """Manages channel sync and checkpoints."""

    def __init__(self, ingestor: ArchiveIngestor) -> None:
        self.ingestor = ingestor
        self.archive = ingestor.archive
        self.policy = ingestor.policy

    async def reconcile_channel(self, channel: Any, mode: str = "auto", days: int = 30) -> int:
        parent_id = getattr(channel, "parent_id", None)
        guild = getattr(channel, "guild", None)
        is_priv = bool(getattr(channel, "is_private", lambda: False)())

        if not self.policy.allows(guild.id if guild else None, parent_id or channel.id,
                                  channel.id if parent_id else None, is_priv):
            return 0

        started = datetime.now(timezone.utc)
        channel_id_str = str(channel.id)

        with self.archive.connect() as db:
            row = db.execute(
                "SELECT completed_at FROM archive_checkpoints WHERE channel_id=?",
                (channel_id_str,),
            ).fetchone()

        after = datetime.fromisoformat(row[0].replace("Z", "+00:00")) - timedelta(seconds=1) if row else None
        limit = None
        oldest_first = True

        if not row:
            if mode == "none":
                after = started
            elif mode == "days":
                after = started - timedelta(days=max(0, int(days)))
            elif mode == "latest":
                limit = 100
                oldest_first = False

        count = 0
        async for message in channel.history(limit=limit, after=after, before=started, oldest_first=oldest_first):
            dto = message_to_dto(message)
            saved = await asyncio.to_thread(self.ingestor.save_message, dto)
            if saved:
                count += 1

        with self.archive.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO archive_checkpoints (channel_id, completed_at) VALUES (?, ?)",
                (channel_id_str, utc_iso(started)),
            )

        return count
