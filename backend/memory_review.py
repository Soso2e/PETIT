"""Owner-reviewed retirement of memories that episode summaries wrote before v0.58.0.

Those rows (``source='auto_episode'``) are mostly state at the time of a
conversation. Nothing here decides for the owner and nothing is deleted:

1. ``export`` writes the active rows to a CSV with a proposed action per row.
2. The owner edits the ``action`` column (``expire`` or ``keep``).
3. ``apply`` backs the database up, sets ``valid_until`` on the ``expire`` rows
   and writes an audit file. Expired rows stay stored and searchable with
   ``search_memory(include_inactive=true)``.
4. ``restore`` puts the previous ``valid_until`` back from that audit file.
"""
from __future__ import annotations

import csv
from contextlib import closing
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config, db

LEGACY_SOURCE = "auto_episode"
ACTIONS = {"expire", "keep"}
FIELDS = ["id", "action", "created_at", "type", "content"]


def _active(connection, now: str) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(
        "SELECT id,created_at,type,content,valid_until FROM memory WHERE source=? AND superseded_by IS NULL "
        "AND (valid_until IS NULL OR valid_until>?) ORDER BY id", (LEGACY_SOURCE, now))]


def export(path: Path, *, default_action: str = "expire") -> dict[str, Any]:
    """Write the review sheet. Reads the database only."""
    if default_action not in ACTIONS:
        raise ValueError("default_action must be expire or keep")
    with db.get_connection() as connection:
        rows = _active(connection, db.now_iso())
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig so a spreadsheet opens the Japanese text correctly.
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({"id": row["id"], "action": default_action, "created_at": row["created_at"],
                             "type": row["type"], "content": row["content"]})
    return {"path": str(path), "rows": len(rows), "default_action": default_action}


def _read(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        if set(FIELDS) - set(row) or str(row["action"]).strip().lower() not in ACTIONS or not str(row["id"]).isdigit():
            raise ValueError(f"review file has an invalid row: id={row.get('id')!r} action={row.get('action')!r}")
    return rows


def plan(path: Path) -> dict[str, Any]:
    """What ``apply`` would do. A row changed or retired since the export is skipped, not guessed."""
    now = db.now_iso()
    with db.get_connection() as connection:
        current = {row["id"]: row for row in _active(connection, now)}
    expire, keep, skipped = [], [], []
    for row in _read(path):
        memory_id, action = int(row["id"]), row["action"].strip().lower()
        live = current.get(memory_id)
        if live is None or db.normalized_hash(live["content"]) != db.normalized_hash(row["content"]):
            skipped.append(memory_id)
        elif action == "expire":
            expire.append(memory_id)
        else:
            keep.append(memory_id)
    return {"expire": expire, "keep": keep, "skipped": skipped,
            "unlisted": sorted(set(current) - set(expire) - set(keep))}


def _backup(stamp: str) -> Path:
    target = Path(config.DB_PATH).with_name(Path(config.DB_PATH).name + f".before-memory-review-{stamp}.bak")
    if target.exists():
        raise FileExistsError(str(target))
    # closing(): sqlite3's own context manager commits but keeps the file open (and locked on Windows).
    with closing(sqlite3.connect(str(config.DB_PATH))) as source, closing(sqlite3.connect(str(target))) as copy:
        source.backup(copy)
    return target


def apply(path: Path, audit_dir: Path) -> dict[str, Any]:
    planned = plan(path)
    instant = datetime.now(timezone.utc)
    # Same clock format as every other valid_until comparison in the store.
    stamp, now = instant.strftime("%Y%m%dT%H%M%SZ"), db.now_iso()
    if not planned["expire"]:
        return {**planned, "applied": 0, "backup": None, "audit": None}
    backup = _backup(stamp)
    changed = []
    with db.write_transaction() as connection:
        for memory_id in planned["expire"]:
            previous = connection.execute("SELECT valid_until FROM memory WHERE id=?", (memory_id,)).fetchone()[0]
            connection.execute("UPDATE memory SET valid_until=?,updated_at=? WHERE id=? AND source=?",
                               (now, now, memory_id, LEGACY_SOURCE))
            changed.append({"id": memory_id, "previous_valid_until": previous})
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit = audit_dir / f"memory-review-applied-{stamp}.json"
    audit.write_text(json.dumps({"applied_at": now, "backup": str(backup), "rows": changed}, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    return {**planned, "applied": len(changed), "backup": str(backup), "audit": str(audit)}


def restore(audit: Path) -> dict[str, Any]:
    """Undo one ``apply``. A row whose expiry was changed again afterwards is left alone."""
    data = json.loads(audit.read_text(encoding="utf-8"))
    restored = 0
    with db.write_transaction() as connection:
        for row in data["rows"]:
            restored += connection.execute(
                "UPDATE memory SET valid_until=?,updated_at=? WHERE id=? AND valid_until=?",
                (row["previous_valid_until"], db.now_iso(), row["id"], data["applied_at"])).rowcount
    return {"restored": restored, "listed": len(data["rows"])}
