"""Discord message archive storage with SQLite, WAL, and FTS5.

Provides an authoritative source of truth for archived messages and attachments
with strict tombstone semantics and rebuildable full-text search.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterator

log = logging.getLogger("petit.discord_archive")

FIELDS = (
    "message_id guild_id guild_name channel_id channel_name "
    "thread_id thread_name author_id author_name content "
    "created_at edited_at reply_to_message_id discord_url is_private_thread"
).split()


def utc_iso(value: datetime | str | None = None) -> str:
    if value is None:
        value = datetime.now(timezone.utc)
    elif isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


class DiscordArchive:
    """Manages an archive SQLite database with FTS5 search indexes."""

    def __init__(self, path: Path | str, zone: str = "personal") -> None:
        self.path = Path(path)
        self.zone = zone
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self.bind_zone(zone)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 3:
                raise ValueError("Archive schema is newer than this application")

            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS discord_messages (
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

                CREATE TABLE IF NOT EXISTS discord_attachments (
                    attachment_id TEXT PRIMARY KEY,
                    message_id TEXT NOT NULL REFERENCES discord_messages(message_id) ON DELETE CASCADE,
                    filename TEXT,
                    content_type TEXT,
                    size INTEGER,
                    url TEXT,
                    extracted_text TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_messages_lookup
                    ON discord_messages(guild_id, channel_id, thread_id, created_at);

                CREATE TABLE IF NOT EXISTS archive_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );

                CREATE TABLE IF NOT EXISTS archive_checkpoints (
                    channel_id TEXT PRIMARY KEY,
                    completed_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS archive_state (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
                """
            )

            # Ensure FTS5 tables and triggers exist
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='archive_fts'").fetchone()
            db.executescript(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS archive_fts USING fts5(
                    content,
                    attachment_text,
                    prefix='2,3'
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS archive_trigrams USING fts5(
                    content,
                    attachment_text,
                    tokenize='trigram'
                );

                CREATE TRIGGER IF NOT EXISTS trg_archive_insert AFTER INSERT ON discord_messages
                WHEN NEW.is_deleted=0 BEGIN
                    INSERT INTO archive_fts(rowid, content, attachment_text) VALUES (NEW.rowid, NEW.content, '');
                    INSERT INTO archive_trigrams(rowid, content, attachment_text) VALUES (NEW.rowid, NEW.content, '');
                END;

                CREATE TRIGGER IF NOT EXISTS trg_archive_update AFTER UPDATE ON discord_messages BEGIN
                    DELETE FROM archive_fts WHERE rowid=OLD.rowid;
                    DELETE FROM archive_trigrams WHERE rowid=OLD.rowid;
                    INSERT INTO archive_fts(rowid, content, attachment_text)
                        SELECT NEW.rowid, NEW.content,
                               COALESCE((SELECT group_concat(extracted_text, ' ') FROM discord_attachments WHERE message_id=NEW.message_id), '')
                        WHERE NEW.is_deleted=0;
                    INSERT INTO archive_trigrams(rowid, content, attachment_text)
                        SELECT NEW.rowid, NEW.content,
                               COALESCE((SELECT group_concat(extracted_text, ' ') FROM discord_attachments WHERE message_id=NEW.message_id), '')
                        WHERE NEW.is_deleted=0;
                END;

                CREATE TRIGGER IF NOT EXISTS trg_archive_delete AFTER DELETE ON discord_messages BEGIN
                    DELETE FROM archive_fts WHERE rowid=OLD.rowid;
                    DELETE FROM archive_trigrams WHERE rowid=OLD.rowid;
                END;
                """
            )
            if not exists:
                self._rebuild_fts(db)

            db.execute("PRAGMA user_version=3")

    def _rebuild_fts(self, db: sqlite3.Connection) -> None:
        db.execute("DELETE FROM archive_fts")
        db.execute("DELETE FROM archive_trigrams")
        db.execute(
            """
            INSERT INTO archive_fts(rowid, content, attachment_text)
            SELECT m.rowid, m.content,
                   COALESCE((SELECT group_concat(a.extracted_text, ' ') FROM discord_attachments a WHERE a.message_id=m.message_id), '')
            FROM discord_messages m WHERE m.is_deleted=0
            """
        )
        db.execute(
            """
            INSERT INTO archive_trigrams(rowid, content, attachment_text)
            SELECT m.rowid, m.content,
                   COALESCE((SELECT group_concat(a.extracted_text, ' ') FROM discord_attachments a WHERE a.message_id=m.message_id), '')
            FROM discord_messages m WHERE m.is_deleted=0
            """
        )

    def rebuild_fts(self) -> None:
        with self.connect() as db:
            self._rebuild_fts(db)

    def bind_zone(self, zone: str) -> None:
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO archive_meta VALUES ('trust_zone', ?)", (zone,))
            row = db.execute("SELECT value FROM archive_meta WHERE key='trust_zone'").fetchone()
            if row and row[0] != zone:
                raise ValueError(f"Archive belongs to zone '{row[0]}', expected '{zone}'")

    def upsert_message(self, message: dict[str, Any]) -> bool:
        """Upsert a message authoritative representation.

        Returns True if inserted or updated, False if skipped as stale or identical.
        """
        data = {k: message.get(k) for k in FIELDS}
        for k in ("message_id", "guild_id", "channel_id"):
            if data[k] is None:
                raise ValueError(f"Missing required field: {k}")
            data[k] = str(data[k])

        if data["created_at"] is None:
            raise ValueError("Missing created_at")
        data["created_at"] = utc_iso(data["created_at"])
        if data["edited_at"]:
            data["edited_at"] = utc_iso(data["edited_at"])

        for k in ("thread_id", "author_id", "reply_to_message_id"):
            if data[k] is not None:
                data[k] = str(data[k])

        data["content"] = str(data["content"] or "")
        data["is_private_thread"] = int(bool(data["is_private_thread"]))
        loc = data["thread_id"] or data["channel_id"]
        data["discord_url"] = f"https://discord.com/channels/{data['guild_id']}/{loc}/{data['message_id']}"

        with self.connect() as db:
            old = db.execute(
                "SELECT * FROM discord_messages WHERE message_id=?", (data["message_id"],)
            ).fetchone()

            # Prevent resurrecting tombstones or overwriting with older revisions
            if old:
                if old["is_deleted"]:
                    return False
                old_time = old["edited_at"] or old["created_at"]
                new_time = data["edited_at"] or data["created_at"]
                if old_time > new_time:
                    return False

            raw_attachments = message.get("attachments", []) or []
            norm_attachments = [
                {
                    "attachment_id": str(a.get("attachment_id") or a.get("id")),
                    "filename": str(a.get("filename") or ""),
                    "content_type": str(a.get("content_type") or ""),
                    "size": int(a.get("size") or 0),
                    "url": str(a.get("url") or ""),
                    "extracted_text": str(a.get("extracted_text") or "") if a.get("extracted_text") else None,
                }
                for a in raw_attachments
                if a.get("attachment_id") or a.get("id")
            ]
            norm_attachments.sort(key=lambda a: a["attachment_id"])

            if old:
                old_attachments = [
                    {
                        "attachment_id": str(r["attachment_id"]),
                        "filename": str(r["filename"] or ""),
                        "content_type": str(r["content_type"] or ""),
                        "size": int(r["size"] or 0),
                        "url": str(r["url"] or ""),
                        "extracted_text": str(r["extracted_text"] or "") if r["extracted_text"] else None,
                    }
                    for r in db.execute(
                        "SELECT attachment_id, filename, content_type, size, url, extracted_text "
                        "FROM discord_attachments WHERE message_id=? ORDER BY attachment_id",
                        (data["message_id"],),
                    )
                ]
                if all(old[k] == data[k] for k in FIELDS) and old_attachments == norm_attachments:
                    return False

            columns = ", ".join(FIELDS)
            updates = ", ".join(f"{k}=excluded.{k}" for k in FIELDS if k != "message_id")
            db.execute(
                f"INSERT INTO discord_messages ({columns}, archived_at) "
                f"VALUES ({','.join('?' for _ in FIELDS)}, ?) "
                f"ON CONFLICT(message_id) DO UPDATE SET {updates}, "
                "archived_at=excluded.archived_at, revision=discord_messages.revision+1",
                [data[k] for k in FIELDS] + [utc_iso()],
            )

            db.execute("DELETE FROM discord_attachments WHERE message_id=?", (data["message_id"],))
            for a in norm_attachments:
                db.execute(
                    "INSERT INTO discord_attachments "
                    "(attachment_id, message_id, filename, content_type, size, url, extracted_text) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        a["attachment_id"],
                        data["message_id"],
                        a["filename"],
                        a["content_type"],
                        a["size"],
                        a["url"],
                        a["extracted_text"],
                    ),
                )

            # Update FTS & trigrams attachment_text if rowid exists
            m_row = db.execute("SELECT rowid FROM discord_messages WHERE message_id=?", (data["message_id"],)).fetchone()
            if m_row and norm_attachments:
                att_text = " ".join(a["extracted_text"] for a in norm_attachments if a["extracted_text"])
                if att_text:
                    db.execute(
                        "UPDATE archive_fts SET attachment_text=? WHERE rowid=?",
                        (att_text, m_row["rowid"]),
                    )
                    db.execute(
                        "UPDATE archive_trigrams SET attachment_text=? WHERE rowid=?",
                        (att_text, m_row["rowid"]),
                    )

        return True

    def mark_deleted(self, message_id: str) -> None:
        """Tombstone a deleted message."""
        with self.connect() as db:
            db.execute(
                "UPDATE discord_messages SET content='', is_deleted=1, revision=revision+1, archived_at=? "
                "WHERE message_id=? AND is_deleted=0",
                (utc_iso(), str(message_id)),
            )
            db.execute("DELETE FROM discord_attachments WHERE message_id=?", (str(message_id),))

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM discord_messages WHERE message_id=?", (str(message_id),)).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["attachments"] = [
                dict(r)
                for r in db.execute(
                    "SELECT attachment_id, filename, content_type, size, url, extracted_text "
                    "FROM discord_attachments WHERE message_id=?",
                    (str(message_id),),
                )
            ]
            return result

    def get_context(self, message_id: str, before: int = 5, after: int = 5) -> list[dict[str, Any]]:
        hit = self.get_message(message_id)
        if not hit or hit["is_deleted"]:
            return []
        with self.connect() as db:
            scope = "channel_id=? AND thread_id IS ? AND is_deleted=0"
            args = (hit["channel_id"], hit["thread_id"])
            left = list(
                db.execute(
                    f"SELECT * FROM discord_messages WHERE {scope} "
                    "AND (created_at, message_id) < (?, ?) ORDER BY created_at DESC, message_id DESC LIMIT ?",
                    args + (hit["created_at"], hit["message_id"], max(0, min(100, before))),
                )
            )
            right = list(
                db.execute(
                    f"SELECT * FROM discord_messages WHERE {scope} "
                    "AND (created_at, message_id) > (?, ?) ORDER BY created_at ASC, message_id ASC LIMIT ?",
                    args + (hit["created_at"], hit["message_id"], max(0, min(100, after))),
                )
            )
            messages = list(reversed(left)) + [hit] + right
            res = []
            for m in messages:
                m_dict = dict(m)
                m_dict["attachments"] = [
                    dict(r)
                    for r in db.execute(
                        "SELECT attachment_id, filename, content_type, size, url, extracted_text "
                        "FROM discord_attachments WHERE message_id=?",
                        (m_dict["message_id"],),
                    )
                ]
                res.append(m_dict)
            return res
