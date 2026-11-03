"""Official CLI protocol and host-local detection.

No credential files, SDK, model API, subprocess prompt runner or Tool dispatcher.
Fixture replay is explicitly labelled mock and uses Core's existing Events only.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import time
from uuid import UUID

POLICY_REASON = "explicit_connection_required"
POLICY_MESSAGE = "Antigravity CLIは初期設定で明示的に接続してください。環境変数や旧Provider設定からは有効化しません。"
POLICY_NOTICE = "個人契約CLIの第三者アプリ内利用は公式FAQで非サポートです。利用者の選択はGoogleの許諾取得を意味しません。"
MAX_BYTES = 2_000_000
MAX_EVENTS = 2000
TOKEN_FIELDS = ("input_tokens", "output_tokens", "thinking_tokens", "cache_read_tokens", "total_tokens")


def require_production_permission():
    from . import setup_store
    data = setup_store.load()
    if not data.get("antigravity_cli_enabled") or "antigravity_cli" not in data["connected"]:
        raise ValueError(POLICY_MESSAGE)


def executable() -> str | None:
    """Bounded detection, including the official installer location; no disk scan."""
    found = shutil.which("agy")
    if found:
        return found
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA")
        candidate = Path(root) / "agy" / "bin" / "agy.exe" if root else None
    else:
        candidate = Path.home() / ".local" / "bin" / "agy"
    return str(candidate) if candidate and candidate.is_file() else None


def status(data: dict | None = None) -> dict:
    enabled = bool(data and data.get("antigravity_cli_enabled") and "antigravity_cli" in data["connected"])
    return {"provider": "antigravity_cli", "installed": executable() is not None,
            "production_enabled": enabled, "reason": None if enabled else POLICY_REASON, "message": POLICY_NOTICE,
            "officially_supported": False, "transport": "cli",
            "authentication": "unknown", "model": "unknown", "quota_remaining": "unknown",
            "version": "unknown", "tested": False,
            "guide": "https://www.antigravity.google/docs/getting-started/"}


def error_category(value: str) -> str:
    # Classify in memory, never return/store the source diagnostic.
    text = value.lower()
    if "429" in text or "resource_exhausted" in text or "quota" in text:
        return "usage_limit"
    if any(x in text for x in ("authentication", "unauthenticated", "sign in", "401")):
        return "authentication_required"
    if "permission" in text or "denied" in text or "403" in text:
        return "permission_denied"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "cancel" in text:
        return "cancelled"
    return "cli_error"


def conversation_id(value) -> str:
    if not isinstance(value, str):
        raise ValueError("invalid_conversation_id")
    try:
        return str(UUID(value))
    except ValueError:
        raise ValueError("invalid_conversation_id") from None


class Protocol:
    """One JSON result or init/step_update/result NDJSON, one CLI turn only."""

    def __init__(self, expected_conversation=None):
        self.conversation = expected_conversation
        self.result = None
        self.count = 0
        self.bytes = 0
        self.initialized = False

    def bind(self, value):
        value = conversation_id(value)
        if self.conversation and value != self.conversation:
            raise ValueError("conversation_mismatch")
        self.conversation = value

    def feed(self, line: str) -> dict:
        self.count += 1
        self.bytes += len(line.encode("utf-8"))
        if self.count > MAX_EVENTS or self.bytes > MAX_BYTES:
            raise ValueError("cli_output_limit")
        if self.result is not None:
            raise ValueError("event_after_result")
        try:
            value = json.loads(line, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (ValueError, RecursionError):
            raise ValueError("invalid_cli_json") from None
        if not isinstance(value, dict):
            raise ValueError("invalid_cli_event")
        kind = value.get("event")
        if kind is None and "status" in value:
            kind, payload = "result", value
        else:
            payload = value.get(kind) if isinstance(kind, str) else None
        if kind == "init":
            if self.initialized or self.count != 1 or not isinstance(payload, dict):
                raise ValueError("invalid_cli_init")
            self.bind(value.get("conversation_id"))
            self.initialized = True
            return {"kind": "init", "conversation_id": self.conversation}
        if kind == "step_update":
            if not self.initialized or not isinstance(payload, dict):
                raise ValueError("invalid_cli_step")
            self.bind(payload.get("conversation_id"))
            step = payload.get("step_type")
            state = payload.get("state")
            index = payload.get("step_index")
            if state not in {"ACTIVE", "DONE"} or type(index) is not int or index < 0:
                raise ValueError("invalid_cli_step")
            update = {"kind": "step", "state": state, "index": index}
            if step == "agent_response":
                text = payload.get("text_delta", "")
                if not isinstance(text, str):
                    raise ValueError("invalid_cli_text")
                update["text_delta"] = text
            elif step == "tool":
                name = payload.get("tool_name")
                if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,99}", name):
                    raise ValueError("invalid_cli_tool")
                # This is an observation, never authorization or a PETIT Tool call.
                update["tool"] = name
            return update
        if kind != "result" or not isinstance(payload, dict):
            raise ValueError("unsupported_cli_event")
        terminal = payload.get("status")
        if terminal not in {"SUCCESS", "ERROR"}:
            raise ValueError("invalid_cli_status")
        cid = payload.get("conversation_id")
        if cid:
            self.bind(cid)
        elif terminal == "SUCCESS":
            raise ValueError("missing_conversation_id")
        response = payload.get("response", "")
        if not isinstance(response, str):
            raise ValueError("invalid_cli_text")
        raw_usage = payload.get("usage")
        usage = None
        if isinstance(raw_usage, dict):
            usage = {k: v for k, v in raw_usage.items() if k in TOKEN_FIELDS and type(v) is int and v >= 0}
            usage = usage or None
        self.result = {"kind": "result", "conversation_id": self.conversation,
                       "status": terminal, "response": response if terminal == "SUCCESS" else "",
                       "usage": usage, "quota_remaining": "unknown",
                       "error": None if terminal == "SUCCESS" else error_category(str(payload.get("error", terminal)))}
        return self.result

    def finish(self):
        if self.result is None:
            raise ValueError("missing_cli_result")
        return self.result


def fixture_session(thread_id: str) -> str | None:
    """Restore only this thread's mock session from the authoritative Core DB."""
    from . import db
    with db.get_connection() as c:
        row = c.execute("SELECT payload_json FROM turn_events WHERE thread_id=? AND type='antigravity_cli_mock_session' ORDER BY seq DESC LIMIT 1", (thread_id,)).fetchone()
    return json.loads(row[0])["conversation_id"] if row else None


def replay_fixture(request_id: str, lines, *, timeout_seconds=5, now=time.monotonic) -> dict:
    """Offline contract harness. NOT a Brain backend. Does not start any process.

    Caller owns synthetic DB, Core accept/claim/finish. Interrupted requests are
    deliberately not replayed. Restart restores session IDs, never unfinished work.
    """
    from . import conversation_store as store, db
    row = store.load_turn(request_id)
    if row["status"] != "running":
        raise ValueError("fixture_turn_not_running")
    thread_id = row["thread_id"]
    with db.write_transaction() as c:
        if c.execute("SELECT 1 FROM turn_events WHERE request_id=? AND type='antigravity_cli_mock_started'", (request_id,)).fetchone():
            raise ValueError("fixture_already_started")
        store.event(c, thread_id, request_id, "antigravity_cli_mock_started", {"evidence": "mock_only"})
    protocol = Protocol(fixture_session(thread_id))
    deadline = now() + timeout_seconds
    def check():
        if store.load_turn(request_id)["cancel_requested"]:
            raise ValueError("cancelled")
        if now() >= deadline:
            raise TimeoutError("fixture_timeout")
    for line in lines:
        check()
        previous = protocol.conversation
        update = protocol.feed(line)
        with db.write_transaction() as c:
            if protocol.conversation and previous != protocol.conversation:
                bindings = c.execute("SELECT thread_id,payload_json FROM turn_events WHERE type='antigravity_cli_mock_session'").fetchall()
                if any(x["thread_id"] != thread_id and json.loads(x["payload_json"])["conversation_id"] == protocol.conversation for x in bindings):
                    raise ValueError("conversation_owned_by_other_thread")
                store.event(c, thread_id, request_id, "antigravity_cli_mock_session", {"conversation_id": protocol.conversation})
            if update["kind"] == "step":
                store.event(c, thread_id, request_id, "antigravity_cli_mock_progress", {**update, "evidence": "mock_only"})
    check()
    result = protocol.finish()
    return {**result, "provider": "antigravity_cli", "evidence": "mock_only",
            "authentication": "unknown", "model": "unknown", "live_verified": False}
