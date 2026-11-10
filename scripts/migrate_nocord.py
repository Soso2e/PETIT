#!/usr/bin/env python3
"""Migration script from Nocord-Bot archive to PETIT Discord Archive.

Reads existing Nocord SQLite databases and allowlists in read-only mode,
safely upserting records into PETIT's storage/archive/<zone>.sqlite with zero
loss and zero duplication. Idempotent and reversible.
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sqlite3
import sys

# Ensure repository root is in sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.discord_archive import (
    DiscordArchive,
    set_registrations,
    read_state,
    allowlist_path,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("petit.migrate_nocord")


def migrate_nocord_db(
    source_db_path: Path,
    target_archive_dir: Path,
    zone: str = "personal",
    source_allowlist_path: Path | None = None,
) -> dict[str, int]:
    source_db_path = Path(source_db_path)
    target_archive_dir = Path(target_archive_dir)

    if not source_db_path.exists():
        raise FileNotFoundError(f"Source database not found: {source_db_path}")

    target_archive_dir.mkdir(parents=True, exist_ok=True)
    target_db_path = target_archive_dir / f"{zone}.sqlite"
    target_archive = DiscordArchive(target_db_path, zone=zone)

    # 1. Read source database (read-only)
    source_uri = f"file:{source_db_path.resolve()}?mode=ro"
    src_conn = sqlite3.connect(source_uri, uri=True)
    src_conn.row_factory = sqlite3.Row

    stats = {
        "source_messages": 0,
        "source_attachments": 0,
        "migrated_messages": 0,
        "migrated_attachments": 0,
        "skipped_messages": 0,
        "target_total_messages": 0,
    }

    try:
        # Check source tables
        tables = {r[0] for r in src_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "discord_messages" not in tables:
            log.warning("No 'discord_messages' table found in source database.")
            return stats

        src_messages = list(src_conn.execute("SELECT * FROM discord_messages ORDER BY created_at ASC"))
        stats["source_messages"] = len(src_messages)

        has_attachments = "discord_attachments" in tables
        for row in src_messages:
            msg_dict = dict(row)
            mid = str(msg_dict["message_id"])

            attachments = []
            if has_attachments:
                att_rows = src_conn.execute(
                    "SELECT * FROM discord_attachments WHERE message_id=? ORDER BY attachment_id", (mid,)
                ).fetchall()
                stats["source_attachments"] += len(att_rows)
                for a in att_rows:
                    a_dict = dict(a)
                    attachments.append({
                        "attachment_id": str(a_dict.get("attachment_id")),
                        "filename": str(a_dict.get("filename") or ""),
                        "content_type": str(a_dict.get("content_type") or ""),
                        "size": int(a_dict.get("size") or 0),
                        "url": str(a_dict.get("url") or ""),
                        "extracted_text": a_dict.get("extracted_text"),
                    })

            msg_dict["attachments"] = attachments
            changed = target_archive.upsert_message(msg_dict)
            if changed:
                stats["migrated_messages"] += 1
                stats["migrated_attachments"] += len(attachments)
            else:
                stats["skipped_messages"] += 1

        with target_archive.connect() as tgt_conn:
            stats["target_total_messages"] = tgt_conn.execute(
                "SELECT COUNT(*) FROM discord_messages"
            ).fetchone()[0]

    finally:
        src_conn.close()

    # 2. Migrate allowlist if present
    if source_allowlist_path and Path(source_allowlist_path).exists():
        try:
            raw_allow = json.loads(Path(source_allowlist_path).read_text(encoding="utf-8"))
            guilds = raw_allow.get("guilds", {})
            for gid, channels in guilds.items():
                for cid, enabled in channels.items():
                    set_registrations(target_archive_dir, zone, gid, [cid], bool(enabled))
            log.info("Migrated allowlist entries from %s", source_allowlist_path)
        except Exception as exc:
            log.warning("Failed to migrate allowlist (%s)", type(exc).__name__)

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate Nocord-Bot archive to PETIT Discord Archive")
    parser.add_argument("--source", "-s", required=True, help="Path to Nocord archive.sqlite")
    parser.add_argument("--allowlist", "-a", help="Path to Nocord archive.allowlist.json (optional)")
    parser.add_argument("--zone", "-z", default="personal", help="Trust zone name (default: personal)")
    parser.add_argument("--target-dir", "-t", default="storage/archive", help="PETIT archive directory")

    args = parser.parse_args()
    log.info("Starting migration from %s to %s (zone: %s)...", args.source, args.target_dir, args.zone)

    try:
        stats = migrate_nocord_db(
            source_db_path=Path(args.source),
            target_archive_dir=Path(args.target_dir),
            zone=args.zone,
            source_allowlist_path=Path(args.allowlist) if args.allowlist else None,
        )
        print("\n=== Migration Results ===")
        print(f"Source Messages:      {stats['source_messages']}")
        print(f"Source Attachments:   {stats['source_attachments']}")
        print(f"Migrated Messages:    {stats['migrated_messages']}")
        print(f"Migrated Attachments: {stats['migrated_attachments']}")
        print(f"Skipped (unchanged):  {stats['skipped_messages']}")
        print(f"Target Total Messages:{stats['target_total_messages']}")
        print("=========================\nMigration completed successfully.")
    except Exception as exc:
        log.error("Migration failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
