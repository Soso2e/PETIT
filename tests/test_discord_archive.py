"""Tests for DiscordArchive, ArchivePolicy, ArchiveSearch, and Ingestor."""
from datetime import datetime, timezone
from pathlib import Path
import pytest

from backend.discord_archive import (
    DiscordArchive,
    ArchivePolicy,
    ArchiveSearch,
    ArchiveIngestor,
    set_registrations,
    effective_policy,
    extract_attachment_text,
)


@pytest.fixture
def temp_archive(tmp_path: Path):
    db_path = tmp_path / "test_archive.sqlite"
    return DiscordArchive(db_path, zone="personal")


def test_archive_upsert_and_tombstone(temp_archive: DiscordArchive):
    msg = {
        "message_id": "1001",
        "guild_id": "999",
        "guild_name": "Test Guild",
        "channel_id": "111",
        "channel_name": "general",
        "author_id": "222",
        "author_name": "Alice",
        "content": "こんにちは、プティ！",
        "created_at": "2026-11-10T10:00:00Z",
        "attachments": [
            {
                "attachment_id": "5001",
                "filename": "note.txt",
                "content_type": "text/plain",
                "size": 12,
                "url": "https://cdn.discordapp.com/note.txt",
                "extracted_text": "重要なメモです",
            }
        ],
    }

    # First insert
    assert temp_archive.upsert_message(msg) is True
    # Duplicate insert returns False
    assert temp_archive.upsert_message(msg) is False

    stored = temp_archive.get_message("1001")
    assert stored is not None
    assert stored["content"] == "こんにちは、プティ！"
    assert len(stored["attachments"]) == 1
    assert stored["attachments"][0]["filename"] == "note.txt"
    assert stored["discord_url"] == "https://discord.com/channels/999/111/1001"

    # Mark deleted (tombstone)
    temp_archive.mark_deleted("1001")
    deleted = temp_archive.get_message("1001")
    assert deleted["is_deleted"] == 1
    assert deleted["content"] == ""

    # Stale insert must not resurrect tombstone
    assert temp_archive.upsert_message(msg) is False
    assert temp_archive.get_message("1001")["is_deleted"] == 1


def test_archive_search_fts_and_scope(tmp_path: Path):
    db_path = tmp_path / "search_archive.sqlite"
    archive = DiscordArchive(db_path, zone="personal")

    # Policy allows guild 999 channel 111, but NOT channel 222
    policy_config = {
        "enabled": True,
        "trust_zone": "personal",
        "allow_guilds": {
            "999": {"channels": ["111"]}
        },
    }
    policy = ArchivePolicy(policy_config)
    searcher = ArchiveSearch(archive, policy)

    # Message in allowed channel
    archive.upsert_message({
        "message_id": "101",
        "guild_id": "999",
        "channel_id": "111",
        "author_id": "1",
        "author_name": "Bob",
        "content": "Mayaのプラグイン開発について話しましょう",
        "created_at": "2026-11-10T11:00:00Z",
    })

    # Message in unauthorized channel
    archive.upsert_message({
        "message_id": "102",
        "guild_id": "999",
        "channel_id": "222",
        "author_id": "2",
        "author_name": "Charlie",
        "content": "秘密のMayaプラグインコード",
        "created_at": "2026-11-10T11:05:00Z",
    })

    # Search for Maya
    results = searcher.search("Maya")
    assert len(results) == 1
    assert results[0]["message_id"] == "101"
    assert results[0]["author_name"] == "Bob"
    assert results[0]["discord_url"] == "https://discord.com/channels/999/111/101"

    # Search for non-existent keyword
    assert len(searcher.search("Blender")) == 0


def test_attachment_text_search(tmp_path: Path):
    db_path = tmp_path / "att_archive.sqlite"
    archive = DiscordArchive(db_path, zone="personal")
    policy = ArchivePolicy({"enabled": True, "trust_zone": "personal", "allow_guilds": {"1": {"channels": ["1"]}}})
    searcher = ArchiveSearch(archive, policy)

    archive.upsert_message({
        "message_id": "201",
        "guild_id": "1",
        "channel_id": "1",
        "author_id": "1",
        "content": "資料を添付しました",
        "created_at": "2026-11-10T12:00:00Z",
        "attachments": [
            {
                "attachment_id": "99",
                "filename": "specification.txt",
                "extracted_text": "プロジェクトWEVORAの要件定義書です",
            }
        ],
    })

    hits = searcher.search("WEVORA")
    assert len(hits) == 1
    assert hits[0]["message_id"] == "201"


def test_allowlist_atomic_update(tmp_path: Path):
    archive_dir = tmp_path / "archive"
    base_policy = ArchivePolicy({"enabled": True, "trust_zone": "personal", "allow_guilds": {}})

    # Initially not allowed
    pol = effective_policy(base_policy, archive_dir)
    assert pol.allows("100", "200") is False

    # Register channel 200
    set_registrations(archive_dir, "personal", "100", ["200"], True)
    pol2 = effective_policy(base_policy, archive_dir)
    assert pol2.allows("100", "200") is True

    # Unregister channel 200
    set_registrations(archive_dir, "personal", "100", ["200"], False)
    pol3 = effective_policy(base_policy, archive_dir)
    assert pol3.allows("100", "200") is False


def test_extract_attachment_text():
    raw_txt = b"Hello, world!\nLine 2"
    assert extract_attachment_text(raw_txt, "readme.txt") == "Hello, world!\nLine 2"
    assert extract_attachment_text(b"some binary data", "image.png") is None
