"""PETIT Tool bridge for CLI agents (H2).

Core issues a short-lived token bound to one Turn. The stdio MCP server
(``python -m backend.petit_mcp``) is started by the CLI with that token and
relays tools/list and tools/call here. Every call still goes through the same
public catalog, schema validation, risk, approval and effect receipt as the
native Tool Loop, so moving the call site to MCP does not move the boundary.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from . import conversation_store as store, request_context, tools

router = APIRouter()

TTL_SECONDS = 30 * 60
MAX_CALLS = 40

_lock = threading.Lock()
_tokens: dict[str, dict] = {}


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue(request_id: str, *, ttl: int = TTL_SECONDS) -> str:
    store.load_turn(request_id)  # must exist
    token = secrets.token_urlsafe(32)
    with _lock:
        now = time.time()
        for key in [k for k, v in _tokens.items() if v["expires_at"] < now]:
            _tokens.pop(key, None)
        _tokens[_hash(token)] = {"request_id": request_id, "expires_at": now + ttl, "calls": 0}
    return token


def revoke(token: str) -> None:
    with _lock:
        _tokens.pop(_hash(token), None)


def _grant(authorization: str | None, *, counting: bool) -> dict:
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not supplied:
        raise HTTPException(401, "認証できませんでした。")
    key = _hash(supplied)
    with _lock:
        grant = next((v for k, v in _tokens.items() if hmac.compare_digest(k, key)), None)
        if grant is None or grant["expires_at"] < time.time():
            raise HTTPException(401, "トークンが無効か期限切れです。")
        if counting:
            if grant["calls"] >= MAX_CALLS:
                raise HTTPException(429, "このTurnのTool呼び出し上限に達しました。")
            grant["calls"] += 1
        return dict(grant)


def _turn_context(request_id: str):
    row = store.load_turn(request_id)
    if row["status"] not in {"queued", "running"}:
        raise HTTPException(409, "このTurnは実行中ではありません。")
    if row["input_json"] is None:
        # The ledger consumes input_json when a Turn first stops. A Turn only resumes after an
        # admin (or the Discord owner) approved something, so that approval stands in for it.
        from . import db
        with db.get_connection() as connection:
            approved = connection.execute("SELECT 1 FROM turn_approvals WHERE request_id=? AND status='approved' LIMIT 1",
                                          (request_id,)).fetchone()
        payload = {"is_admin": bool(approved)}
    else:
        payload = json.loads(row["input_json"])
    if not payload.get("is_admin"):
        # Non-admin turns are plain conversation: no Tools (same as the native loop).
        raise HTTPException(403, "このTurnではToolを使えません。")
    return row, request_context.bind(request_id=request_id, session_id=row["thread_id"],
                                     conversation_mode=payload.get("conversation_mode", "text"), is_admin=True)


def _catalog() -> dict[str, dict]:
    from . import brain
    return {item["function"]["name"]: item["function"] for item in brain.schemas()}


class ToolCall(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    arguments: dict = Field(default_factory=dict)


@router.post("/api/agent-bridge/tools/list")
def list_tools(authorization: str | None = Header(default=None)) -> dict:
    grant = _grant(authorization, counting=False)
    _row, context = _turn_context(grant["request_id"])
    with context:
        catalog = _catalog()
    return {"tools": [{"name": name, "description": f.get("description", ""),
                       "inputSchema": f.get("parameters") or {"type": "object", "properties": {}},
                       "risk": tools.risk_for(name)} for name, f in sorted(catalog.items())]}


@router.post("/api/agent-bridge/tools/call")
def call_tool(payload: ToolCall, authorization: str | None = Header(default=None)) -> dict:
    from . import brain
    from .provider_runtime import validate_arguments
    grant = _grant(authorization, counting=True)
    request_id = grant["request_id"]
    row, context = _turn_context(request_id)
    if row["cancel_requested"]:
        return {"isError": True, "result": {"error": "cancelled", "stop": True}}
    if store.approvals(request_id):
        # One approval at a time: the agent must stop and let the user decide first.
        return {"isError": False, "result": {"status": "awaiting_user_approval", "stop": True,
                                              "message": "承認待ちの操作がある。ここで回答を終えること。"}}
    with context:
        catalog = _catalog()
        if payload.name not in catalog:
            return {"isError": True, "result": {"error": "tool_not_public_or_unavailable"}}
        try:
            arguments = tools.parse_arguments(payload.name, validate_arguments(
                catalog[payload.name]["parameters"], json.dumps(payload.arguments, ensure_ascii=False)))
        except (ValueError, TypeError) as exc:
            return {"isError": True, "result": {"error": str(exc)}}
        call = {"id": "mcp-" + uuid4().hex, "type": "function",
                "function": {"name": payload.name, "arguments": store.encode(arguments)}}
        if tools.requires_confirmation(payload.name):
            approval_id = store.propose(request_id, call, arguments)
            raw = store.encode({"status": "awaiting_user_approval", "approval_id": approval_id, "stop": True,
                                "message": "ユーザーの承認待ち。承認されるまで実行していない。実行済みと言わないこと。"})
        else:
            raw = brain.execute(request_id, call, arguments)
        # Same ledger shape as external_brain: approval fills the tool result, then the Turn resumes.
        messages = json.loads(store.load_turn(request_id)["messages_json"] or "[]")
        messages.extend([{"role": "assistant", "content": "", "tool_calls": [call]},
                         {"role": "tool", "tool_call_id": call["id"], "content": brain.compact(raw, payload.name)}])
        store.save_messages(request_id, messages)
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        value = {"text": str(raw)}
    return {"isError": brain.failed(str(raw)), "result": value}
