"""Ingestion utilities for Discord messages and file attachments."""
from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from typing import Any

from .archive import DiscordArchive, utc_iso
from .policy import ArchivePolicy

log = logging.getLogger("petit.discord_archive")


def extract_attachment_text(content: bytes, filename: str, max_chars: int = 100000) -> str | None:
    """Extract text from attachment bytes (PDF, txt, md, json) with strict resource limits."""
    suffix = Path(filename).suffix.lower()
    if suffix in (".txt", ".md", ".csv", ".tsv", ".py", ".sh", ".json", ".log"):
        try:
            # Shield against massive memory allocations
            text = content[:max_chars * 4].decode("utf-8", errors="replace")
            return text[:max_chars]
        except Exception:
            return None

    if suffix == ".pdf":
        try:
            from pdfminer.high_level import extract_text as pdf_extract
            # Bound page count to prevent infinite processing on massive PDFs
            text = pdf_extract(io.BytesIO(content), maxpages=50)
            return text[:max_chars] if text else None
        except ImportError:
            log.debug("pdfminer.six not installed; skipping PDF text extraction")
            return None
        except Exception as exc:
            log.warning("PDF extraction failed for %s (%s)", filename, type(exc).__name__)
            return None

    return None


class ArchiveIngestor:
    """Consent-aware message ingestion."""

    def __init__(self, archive: DiscordArchive, policy: ArchivePolicy) -> None:
        self.archive = archive
        self.policy = policy
        self.archive.bind_zone(policy.zone)

    def save_message(self, message_dto: dict[str, Any]) -> bool:
        guild_id = message_dto.get("guild_id")
        channel_id = message_dto.get("channel_id")
        thread_id = message_dto.get("thread_id")
        private = bool(message_dto.get("is_private_thread", False))

        if not self.policy.allows(guild_id, channel_id, thread_id, private):
            return False

        if message_dto.get("author_is_bot") and not self.policy.include_bots:
            return False

        changed = self.archive.upsert_message(message_dto)
        if changed:
            with self.archive.connect() as db:
                db.execute(
                    "INSERT OR REPLACE INTO archive_state (key, value) VALUES ('last_event_at', ?)",
                    (utc_iso(),),
                )
        return changed

    def delete_message(self, message_id: str) -> None:
        self.archive.mark_deleted(str(message_id))
