"""Tests for migrate_nocord migration script."""
import json
from pathlib import Path
import sqlite3
import pytest

from scripts.migrate_nocord import migrate_nocord_db
from backend.discord_archive import DiscordArchive, read_state, allowlist_path


def create_fake_nocord_db(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE discord_messages (
            message_id TEXT PRIMARY KEY,
            guild_id TEXT NOT NULL,
            guild_name TEXT,
            channel_id TEXT NOT NULL,
            channel_name TEXT,
            thread_id TEXT,
            thread_name TEXT,
            author_id TEXT,
            author_name TEXT,
            content TEXT,
            created_at TEXT NOT NULL,
            edited_at TEXT,
            reply_to_message_id TEXT,
            discord_url TEXT,
            is_private_thread INTEGER NOT NULL DEFAULT 0,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            archived_at TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE discord_attachments (
            attachment_id TEXT PRIMARY KEY,
            message_id TEXT NOT NULL,
            filename TEXT,
            content_type TEXT,
            size INTEGER,
            url TEXT,
            extracted_text TEXT
        );
        INSERT INTO discord_messages VALUES (
            '10001', '777', 'Legacy Nocord Guild', '888', 'chat', NULL, NULL,
            '999', 'LegacyUser', '過去のNocordメッセージです。',
            '2026-10-01T12:00:00Z', NULL, NULL,
            'https://discord.com/channels/777/888/10001', 0, 0,
            '2026-10-01T12:00:05Z', 1
        );
        INSERT INTO discord_attachments VALUES (
            'att_1', '10001', 'doc.txt', 'text/plain', 20, 'https://cdn.discord/doc.txt', '文書本文です'
        );
    """)
    conn.commit()
    conn.close()


def test_migrate_nocord_db_and_allowlist(tmp_path: Path):
    src_db = tmp_path / "nocord_source" / "archive.sqlite"
    create_fake_nocord_db(src_db)

    src_allow = tmp_path / "nocord_source" / "archive.allowlist.json"
    src_allow.write_text(
        json.dumps({
            "trust_zone": "personal",
            "guilds": {
                "777": {"888": True}
            }
        }),
        encoding="utf-8",
    )

    tgt_dir = tmp_path / "petit_archive"

    # 1. Run first migration
    stats1 = migrate_nocord_db(
        source_db_path=src_db,
        target_archive_dir=tgt_dir,
        zone="personal",
        source_allowlist_path=src_allow,
    )

    assert stats1["source_messages"] == 1
    assert stats1["migrated_messages"] == 1
    assert stats1["source_attachments"] == 1
    assert stats1["migrated_attachments"] == 1
    assert stats1["target_total_messages"] == 1

    # Verify content in target archive
    target_archive = DiscordArchive(tgt_dir / "personal.sqlite", zone="personal")
    stored = target_archive.get_message("10001")
    assert stored is not None
    assert stored["content"] == "過去のNocordメッセージです。"
    assert stored["author_name"] == "LegacyUser"
    assert len(stored["attachments"]) == 1
    assert stored["attachments"][0]["filename"] == "doc.txt"

    # Verify allowlist migrated
    allow_state = read_state(allowlist_path(tgt_dir, "personal"), "personal")
    assert allow_state["guilds"]["777"]["888"] is True

    # 2. Run second migration (idempotent test)
    stats2 = migrate_nocord_db(
        source_db_path=src_db,
        target_archive_dir=tgt_dir,
        zone="personal",
        source_allowlist_path=src_allow,
    )
    assert stats2["source_messages"] == 1
    assert stats2["migrated_messages"] == 0  # 0 migrated because already identical
    assert stats2["skipped_messages"] == 1
    assert stats2["target_total_messages"] == 1
