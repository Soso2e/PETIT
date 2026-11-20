"""Tests for search_discord_archive tool with security and guild isolation."""
import json
import os
from pathlib import Path
import pytest

from backend import request_context
from backend.discord_archive import (
    DiscordArchive,
    set_registrations,
)
from backend.request_context import GuildIsolationError
from backend.tools import dispatch
from backend.tools.discord_search import search_discord_archive


@pytest.fixture
def setup_archive(tmp_path: Path, monkeypatch):
    archive_dir = tmp_path / "archive"
    monkeypatch.setenv("PETIT_ARCHIVE_DIR", str(archive_dir))

    # Setup Personal Zone
    p_archive = DiscordArchive(archive_dir / "personal.sqlite", zone="personal")
    set_registrations(archive_dir, "personal", "100", ["101"], True)
    p_archive.upsert_message({
        "message_id": "1",
        "guild_id": "100",
        "guild_name": "Personal Server",
        "channel_id": "101",
        "channel_name": "general",
        "author_id": "10",
        "author_name": "Owner",
        "content": "個人の旅行計画について：来週京都に行きます。",
        "created_at": "2026-11-10T10:00:00Z",
    })

    return archive_dir


def test_tool_search_in_owner_context(setup_archive: Path):
    # Owner / Web / Desktop / Voice context (dispatched to Brain)
    raw_str = dispatch("search_discord_archive", {"query": "旅行計画"})
    result = json.loads(raw_str)
    assert result["count"] == 1
    hit = result["matches"][0]
    assert hit["message_id"] == "1"
    assert "京都" in hit["content"]
    assert hit["author_name"] == "Owner"
    assert hit["discord_url"] == "https://discord.com/channels/100/101/1"


def test_tool_direct_call_returns_dict(setup_archive: Path):
    # Direct function call
    result = search_discord_archive(query="旅行計画")
    assert isinstance(result, dict)
    assert result["count"] == 1
    assert result["matches"][0]["message_id"] == "1"


def test_tool_dispatch_in_guild_mode_is_blocked(setup_archive: Path):
    # Core isolation forbids Guild Mode from reaching Owner Tool Registry
    with request_context.guild_mode(guild_id="200"):
        with pytest.raises(GuildIsolationError):
            dispatch("search_discord_archive", {"query": "旅行計画"})


def test_admin_search_spans_personal_and_all_guilds(setup_archive: Path):
    # Add messages in two separate guild zone databases
    for gid, mid, text in [("200", "21", "Guild200の旅行計画メモ"), ("300", "31", "Guild300の旅行計画アイデア")]:
        zone = f"guild_{gid}"
        archive = DiscordArchive(setup_archive / f"{zone}.sqlite", zone=zone)
        set_registrations(setup_archive, zone, gid, [f"{gid}1"], True)
        archive.upsert_message({
            "message_id": mid,
            "guild_id": gid,
            "guild_name": f"Guild {gid}",
            "channel_id": f"{gid}1",
            "channel_name": "general",
            "author_id": "10",
            "author_name": "Member",
            "content": text,
            "created_at": "2026-11-10T10:00:00Z",
        })

    result = search_discord_archive(query="旅行計画", limit=10)
    mids = {m["message_id"] for m in result["matches"]}
    assert {"1", "21", "31"}.issubset(mids)
