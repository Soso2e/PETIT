"""Durable requests, approvals and effects over PETIT's existing conversation DB.

Completed text remains in conversations. The ledger stores execution state, not
a second transcript. No legacy rows are rewritten or assigned invented threads.
"""
from __future__ import annotations

import hashlib
import json
import time
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from . import config, db

_schema_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
    id TEXT PRIMARY KEY, source TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',
    privacy TEXT NOT NULL DEFAULT 'standard', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS turns (
    request_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL REFERENCES threads(id),
    input_hash TEXT NOT NULL, input_json TEXT, status TEXT NOT NULL,
    conversation_id INTEGER REFERENCES conversations(id), result_json TEXT NOT NULL DEFAULT '{}',
    messages_json TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_turn_thread_busy ON turns(thread_id)
    WHERE status IN ('queued', 'running');
CREATE TABLE IF NOT EXISTS turn_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, thread_id TEXT NOT NULL REFERENCES threads(id),
    request_id TEXT, type TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_turn_events_thread ON turn_events(thread_id, seq);
CREATE TABLE IF NOT EXISTS effect_receipts (
    request_id TEXT NOT NULL REFERENCES turns(request_id), call_id TEXT NOT NULL,
    tool TEXT NOT NULL, arguments_json TEXT NOT NULL, status TEXT NOT NULL,
    result TEXT, updated_at TEXT NOT NULL, PRIMARY KEY(request_id, call_id)
);
CREATE TABLE IF NOT EXISTS turn_approvals (
    id TEXT PRIMARY KEY, request_id TEXT NOT NULL REFERENCES turns(request_id),
    call_id TEXT NOT NULL, tool TEXT NOT NULL, arguments_json TEXT NOT NULL,
    status TEXT NOT NULL, expires_at REAL NOT NULL
);
"""


def ensure_schema() -> None:
    with _schema_lock, db.get_connection() as connection:
        exists = connection.execute("SELECT 1 FROM sqlite_master WHERE name='threads'").fetchone()
        if not exists and connection.execute("SELECT 1 FROM conversations LIMIT 1").fetchone():
            backup = Path(str(config.DB_PATH) + ".before-renaissance.bak")
            if not backup.exists():
                # SQLite backup includes the committed WAL, unlike copying app.db.
                with closing(sqlite3.connect(backup)) as destination:
                    connection.backup(destination)
                    if destination.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise RuntimeError("renaissance_backup_check_failed")
        connection.executescript(SCHEMA)
        db._ensure_columns(connection, "turns", {"provider_key": "TEXT"})
        connection.execute(
            "INSERT OR IGNORE INTO threads(id,source,created_at) "
            "SELECT session_id,'legacy',MIN(timestamp) FROM conversations "
            "WHERE session_id IS NOT NULL AND session_id<>'' GROUP BY session_id")


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def event(connection, thread_id: str, request_id: str | None, kind: str, payload: dict) -> None:
    connection.execute(
        "INSERT INTO turn_events(thread_id,request_id,type,payload_json,created_at) VALUES(?,?,?,?,?)",
        (thread_id, request_id, kind, encode(payload), db.now_iso()),
    )


def create_thread(thread_id: str | None = None, *, source="web", title="", privacy="standard") -> dict:
    ensure_schema()
    thread_id = (thread_id or uuid4().hex).strip()
    if not thread_id or len(thread_id) > 200:
        raise HTTPException(400, "invalid_thread_id")
    with db.get_connection() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO threads(id,source,title,privacy,created_at) VALUES(?,?,?,?,?)",
            (thread_id, source, str(title)[:160], privacy, db.now_iso()),
        )
        return dict(connection.execute("SELECT * FROM threads WHERE id=?", (thread_id,)).fetchone())


def thread(thread_id: str) -> dict:
    ensure_schema()
    with db.get_connection() as connection:
        row = connection.execute("SELECT * FROM threads WHERE id=?", (thread_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "thread_not_found")
    return dict(row)


def list_threads(limit=30) -> list[dict]:
    ensure_schema()
    with db.get_connection() as connection:
        return [dict(row) for row in connection.execute(
            "SELECT * FROM threads ORDER BY created_at DESC,id DESC LIMIT ?", (min(100, max(1, limit)),))]


def accept(thread_id: str, request_id: str, payload: dict) -> tuple[dict, bool]:
    ensure_schema()
    hash_payload = {k: v for k, v in payload.items() if k != "is_admin"}
    signature = hashlib.sha256(encode(hash_payload).encode()).hexdigest()
    with db.write_transaction() as connection:
        existing = connection.execute("SELECT * FROM turns WHERE request_id=?", (request_id,)).fetchone()
        if existing:
            if existing["thread_id"] != thread_id or existing["input_hash"] != signature:
                raise HTTPException(409, "request_id_reused_with_different_input")
            return dict(existing), False
        busy = connection.execute(
            "SELECT request_id FROM turns WHERE thread_id=? AND status IN ('queued','running')", (thread_id,)
        ).fetchone()
        if busy:
            raise HTTPException(429, {"error": "thread_busy", "request_id": busy["request_id"]})
        now = db.now_iso()
        connection.execute(
            "INSERT INTO turns(request_id,thread_id,input_hash,input_json,status,created_at,updated_at) "
            "VALUES(?,?,?,?,'queued',?,?)", (request_id, thread_id, signature, encode(payload), now, now))
        event(connection, thread_id, request_id, "accepted", {})
        return dict(connection.execute("SELECT * FROM turns WHERE request_id=?", (request_id,)).fetchone()), True


def load_turn(request_id: str) -> dict:
    ensure_schema()
    with db.get_connection() as connection:
        row = connection.execute("SELECT * FROM turns WHERE request_id=?", (request_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "turn_not_found")
    return dict(row)


def result(request_id: str) -> dict:
    row = load_turn(request_id)
    data = json.loads(row["result_json"])
    if row["conversation_id"]:
        with db.get_connection() as connection:
            saved = connection.execute("SELECT assistant_text FROM conversations WHERE id=?",
                                       (row["conversation_id"],)).fetchone()
        data["reply"] = saved["assistant_text"] if saved else ""
    data.setdefault("reply", "")
    data.update(request_id=request_id, thread_id=row["thread_id"], status=row["status"])
    data["pending_actions"] = approvals(request_id)
    with db.get_connection() as connection:
        if not data.get("model_route"):
            backend_event = connection.execute(
                "SELECT payload_json FROM turn_events WHERE request_id=? AND type='model_backend' ORDER BY seq DESC LIMIT 1",
                (request_id,)).fetchone()
            if backend_event:
                data["model_route"] = json.loads(backend_event["payload_json"])
        data["effects"] = [dict(r) for r in connection.execute(
            "SELECT call_id,tool,status,result FROM effect_receipts WHERE request_id=? ORDER BY rowid",
            (request_id,))]
    return data


def claim(request_id: str) -> bool:
    with db.get_connection() as connection:
        return bool(connection.execute(
            "UPDATE turns SET status='running',updated_at=? WHERE request_id=? AND status='queued'",
            (db.now_iso(), request_id)).rowcount)


def save_messages(request_id: str, messages: list[dict]) -> None:
    with db.get_connection() as connection:
        connection.execute("UPDATE turns SET messages_json=?,updated_at=? WHERE request_id=?",
                           (encode(messages), db.now_iso(), request_id))


def history(thread_id: str, *, limit=12, max_chars=9000) -> list[dict]:
    # Existing session IDs are the only legacy-to-thread mapping. NULL sessions
    # are never merged into the current conversation.
    with db.get_connection() as connection:
        rows = connection.execute(
            "SELECT user_text,assistant_text FROM conversations WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (thread_id, min(30, max(1, limit))),).fetchall()
    messages = []
    remaining = max_chars
    for row in rows:
        row = db.present_conversation(dict(row))
        pair = []
        for role, key in (("assistant", "assistant_text"), ("user", "user_text")):
            text = str(row[key] or "")
            if text and remaining > 0:
                text = text[-remaining:]
                pair.append({"role": role, "content": text})
                remaining -= len(text)
        messages.extend(pair)
    return list(reversed(messages))


def finish(request_id: str, data: dict, *, status="completed") -> dict:
    with db.write_transaction() as connection:
        row = connection.execute("SELECT * FROM turns WHERE request_id=?", (request_id,)).fetchone()
        payload = json.loads(row["input_json"] or "{}")
        reply = str(data.get("reply") or "")
        if status == "completed" and reply:
            from . import service_sync
            alert = service_sync.warning()
            if alert and alert not in reply:
                reply += "\n\n" + alert
        conversation_id = row["conversation_id"]
        if reply:
            if conversation_id:
                connection.execute("UPDATE conversations SET assistant_text=?,used_tools=? WHERE id=?",
                                   (reply, encode(data.get("used_tools", [])), conversation_id))
            else:
                cursor = connection.execute(
                    "INSERT INTO conversations(timestamp,user_text,assistant_text,used_tools,session_id,source) VALUES(?,?,?,?,?,?)",
                    (db.now_iso(), payload.get("message", "") + (
                        "\n[画像: " + ", ".join(payload["attachment_ids"]) + "]" if payload.get("attachment_ids") else ""), reply,
                     encode(data.get("used_tools", [])), row["thread_id"], payload.get("source")))
                conversation_id = cursor.lastrowid
        metadata = {k: v for k, v in data.items() if k not in {"reply", "pending_actions", "messages"}}
        connection.execute(
            "UPDATE turns SET status=?,conversation_id=?,result_json=?,updated_at=?,"
            "messages_json=CASE WHEN ?='waiting_approval' THEN messages_json ELSE NULL END,"
            "input_json=CASE WHEN ? IS NOT NULL THEN NULL ELSE input_json END WHERE request_id=?",
            (status, conversation_id, encode(metadata), db.now_iso(), status, conversation_id, request_id))
        event(connection, row["thread_id"], request_id, status, {})
    return result(request_id)


def propose(request_id: str, call: dict, arguments: dict) -> str:
    approval_id = uuid4().hex
    row = load_turn(request_id)
    with db.get_connection() as connection:
        connection.execute(
            "INSERT INTO turn_approvals VALUES(?,?,?,?,?,'pending',?)",
            (approval_id, request_id, call["id"], call["function"]["name"], encode(arguments), time.time() + 600))
        event(connection, row["thread_id"], request_id, "approval_required", {"approval_id": approval_id})
    return approval_id


def approvals(request_id: str) -> list[dict]:
    with db.get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM turn_approvals WHERE request_id=? AND status='pending' AND expires_at>?",
            (request_id, time.time())).fetchall()
    return [{"approval_id": r["id"], "name": r["tool"], "arguments": json.loads(r["arguments_json"])} for r in rows]


def approval(approval_id: str) -> dict | None:
    if not Path(config.DB_PATH).exists():
        return None
    with db.get_connection() as connection:
        if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='turn_approvals'").fetchone():
            return None
        row = connection.execute("SELECT * FROM turn_approvals WHERE id=?", (approval_id,)).fetchone()
    return dict(row) if row else None


def receipt(request_id: str, call_id: str) -> dict | None:
    with db.get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM effect_receipts WHERE request_id=? AND call_id=?", (request_id, call_id)).fetchone()
    return dict(row) if row else None


def begin_effect(request_id: str, call: dict, arguments: dict) -> None:
    with db.get_connection() as connection:
        connection.execute(
            "INSERT INTO effect_receipts VALUES(?,?,?,?, 'running',NULL,?)",
            (request_id, call["id"], call["function"]["name"], encode(arguments), db.now_iso()))


def end_effect(request_id: str, call_id: str, raw: str, status: str) -> None:
    with db.get_connection() as connection:
        connection.execute(
            "UPDATE effect_receipts SET status=?,result=?,updated_at=? WHERE request_id=? AND call_id=?",
            (status, raw, db.now_iso(), request_id, call_id))


def snapshot(thread_id: str, after_seq=0) -> dict:
    owner = thread(thread_id)
    with db.get_connection() as connection:
        connection.execute("BEGIN")
        rows = connection.execute(
            "SELECT id,timestamp,user_text,assistant_text FROM conversations WHERE session_id=? ORDER BY id DESC LIMIT 50",
            (thread_id,)).fetchall()
        events = connection.execute(
            "SELECT * FROM turn_events WHERE thread_id=? AND seq>? ORDER BY seq LIMIT 100",
            (thread_id, max(0, after_seq))).fetchall()
        last_seq = connection.execute(
            "SELECT COALESCE(MAX(seq),0) FROM turn_events WHERE thread_id=?", (thread_id,)).fetchone()[0]
        pending = connection.execute(
            "SELECT a.* FROM turn_approvals a JOIN turns t ON t.request_id=a.request_id "
            "WHERE t.thread_id=? AND a.status='pending' AND a.expires_at>?", (thread_id, time.time())).fetchall()
    return {"thread": owner, "conversations": [db.present_conversation(dict(r)) for r in reversed(rows)],
            "events": [{**dict(r), "payload": json.loads(r["payload_json"])} for r in events],
            "last_seq": last_seq, "pending_actions": [
                {"approval_id": r["id"], "name": r["tool"], "arguments": json.loads(r["arguments_json"])} for r in pending]}


def recover() -> None:
    """Called once at process startup. Never replay a possibly applied effect."""
    ensure_schema()
    with db.write_transaction() as connection:
        connection.execute("UPDATE effect_receipts SET status='unknown' WHERE status='running'")
        for row in connection.execute("SELECT request_id,result_json FROM turns WHERE status IN ('queued','running')").fetchall():
            data = json.loads(row["result_json"])
            data["error"] = "Coreの再起動で処理が中断しました。保存済みの実行結果を確認してください。自動再実行はしていません。"
            connection.execute("UPDATE turns SET status='interrupted',result_json=?,updated_at=? WHERE request_id=?",
                               (encode(data), db.now_iso(), row["request_id"]))
