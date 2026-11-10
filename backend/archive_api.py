"""Discord archive API endpoints for Bot process relay and inspection."""
from __future__ import annotations

import hmac
import logging
import os
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from .discord_api import _authorize, owner_id, owner_guild_ids
from .discord_archive import (
    ArchiveIngestor,
    ArchivePolicy,
    ArchiveSearch,
    DiscordArchive,
    effective_policy,
    set_registrations,
)

log = logging.getLogger("petit.archive_api")
router = APIRouter(prefix="/api/channels/discord/archive", tags=["discord_archive"])

DEFAULT_ARCHIVE_DIR = Path("storage/archive")


def get_archive_dir() -> Path:
    env_dir = os.environ.get("PETIT_ARCHIVE_DIR")
    if env_dir:
        return Path(env_dir)
    return DEFAULT_ARCHIVE_DIR


def resolve_zone(guild_id: str | None, requested_zone: str | None = None, author_id: str | None = None) -> str:
    """Resolve archive storage zone ensuring strict isolation between Personal and Guilds."""
    owner = owner_id()
    owner_guilds = owner_guild_ids()
    is_owner_user = bool(owner and author_id and hmac.compare_digest(str(author_id), owner))
    is_owner_guild = bool(guild_id and str(guild_id) in owner_guilds)
    is_dm = guild_id is None

    is_owner_scope = is_dm or is_owner_guild or is_owner_user

    if requested_zone:
        # Non-owner scope cannot access or write into personal zone
        if requested_zone == "personal" and not is_owner_scope:
            return f"guild_{guild_id}" if guild_id else "personal"
        return requested_zone

    if is_owner_scope:
        return "personal"
    return f"guild_{guild_id}" if guild_id else "personal"


def get_components(zone: str = "personal") -> tuple[DiscordArchive, ArchivePolicy, ArchiveIngestor, ArchiveSearch]:
    archive_dir = get_archive_dir()
    db_path = archive_dir / f"{zone}.sqlite"
    archive = DiscordArchive(db_path, zone=zone)
    base_policy = ArchivePolicy({"enabled": True, "trust_zone": zone, "allow_guilds": {}}, zone=zone)
    policy = effective_policy(base_policy, archive_dir)
    ingestor = ArchiveIngestor(archive, policy)
    searcher = ArchiveSearch(archive, policy)
    return archive, policy, ingestor, searcher


class ArchiveMessageEvent(BaseModel):
    message_id: str = Field(min_length=1, max_length=40, pattern=r"^[0-9]+$")
    guild_id: str = Field(min_length=1, max_length=40, pattern=r"^[0-9]+$")
    guild_name: str = Field(default="", max_length=120)
    channel_id: str = Field(min_length=1, max_length=40, pattern=r"^[0-9]+$")
    channel_name: str = Field(default="", max_length=120)
    thread_id: str | None = Field(default=None, max_length=40, pattern=r"^[0-9]+$")
    thread_name: str | None = Field(default=None, max_length=120)
    author_id: str = Field(min_length=1, max_length=40, pattern=r"^[0-9]+$")
    author_name: str = Field(default="", max_length=120)
    author_is_bot: bool = False
    content: str = Field(default="", max_length=20000)
    created_at: str
    edited_at: str | None = None
    reply_to_message_id: str | None = None
    is_private_thread: bool = False
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    zone: str | None = None


class ArchiveDeleteEvent(BaseModel):
    message_id: str = Field(min_length=1, max_length=40, pattern=r"^[0-9]+$")
    guild_id: str = Field(min_length=1, max_length=40, pattern=r"^[0-9]+$")
    channel_id: str = Field(min_length=1, max_length=40, pattern=r"^[0-9]+$")
    author_id: str | None = None
    zone: str | None = None


class ArchiveRegisterRequest(BaseModel):
    guild_id: str = Field(min_length=1, max_length=40, pattern=r"^[0-9]+$")
    author_id: str = Field(min_length=1, max_length=40, pattern=r"^[0-9]+$")
    channel_ids: list[str] = Field(default_factory=list)
    enabled: bool = True
    manage_guild: bool = False
    permissions: int | None = None
    zone: str | None = None


@router.post("/events")
async def receive_message_event(
    event: ArchiveMessageEvent,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _authorize(authorization)
    try:
        zone = resolve_zone(event.guild_id, event.zone, event.author_id)
        archive, policy, ingestor, _ = get_components(zone=zone)
        saved = ingestor.save_message(event.model_dump())
        return {"status": "ok", "saved": saved, "zone": zone}
    except Exception as exc:
        log.warning("Archive message event failed (%s)", type(exc).__name__)
        return {"status": "error", "error": type(exc).__name__}


@router.post("/delete")
async def receive_delete_event(
    event: ArchiveDeleteEvent,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _authorize(authorization)
    try:
        zone = resolve_zone(event.guild_id, event.zone, event.author_id)
        archive, policy, ingestor, _ = get_components(zone=zone)
        ingestor.delete_message(event.message_id)
        return {"status": "ok", "deleted": True, "zone": zone}
    except Exception as exc:
        log.warning("Archive delete event failed (%s)", type(exc).__name__)
        return {"status": "error", "error": type(exc).__name__}


@router.post("/register")
async def register_channels(
    req: ArchiveRegisterRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _authorize(authorization)
    target_zone = resolve_zone(req.guild_id, req.zone, req.author_id)

    # Permission verification:
    if target_zone == "personal":
        owner = owner_id()
        if not (owner and hmac.compare_digest(req.author_id, owner)):
            raise HTTPException(403, "Personal Zone の登録変更は Owner のみ許可されています。")
    else:
        # Guild zone requires Manage Server permission
        has_perm = req.manage_guild or bool(req.permissions and (req.permissions & 0x20))
        if not has_perm:
            raise HTTPException(403, "サーバーの管理権限（Manage Server）が必要です。")

    archive_dir = get_archive_dir()
    set_registrations(archive_dir, target_zone, req.guild_id, req.channel_ids, req.enabled)
    return {
        "status": "ok",
        "guild_id": req.guild_id,
        "zone": target_zone,
        "updated": len(req.channel_ids),
        "enabled": req.enabled,
    }


@router.get("/allowlist")
async def get_allowlist(
    guild_id: str | None = None,
    zone: str | None = None,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _authorize(authorization)
    resolved_zone = resolve_zone(guild_id, zone, author_id=None)
    archive, policy, _, _ = get_components(zone=resolved_zone)
    return {
        "zone": resolved_zone,
        "enabled": policy.enabled,
        "allow_guilds": policy.allow_guilds,
    }


@router.get("/search")
async def search_archive(
    query: str,
    guild_id: str | None = None,
    channel_id: str | None = None,
    limit: int = 10,
    zone: str | None = None,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _authorize(authorization)
    resolved_zone = resolve_zone(guild_id, zone, author_id=None)
    _, _, _, searcher = get_components(zone=resolved_zone)
    filters = {}
    if guild_id:
        filters["guild_id"] = guild_id
    if channel_id:
        filters["channel_id"] = channel_id
    matches = searcher.search(query, limit=limit, **filters)
    return {"query": query, "zone": resolved_zone, "count": len(matches), "matches": matches}
