"""Shared Thread/Turn API; legacy chat is only a synchronous adapter."""
from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import brain, conversation_store as store, db, lmstudio_client, request_context

router = APIRouter()
log = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="petit-turn")


class ThreadCreate(BaseModel):
    id: str | None = Field(default=None, min_length=1, max_length=200)
    title: str = Field(default="", max_length=160)
    source: Literal["web", "desktop", "voice", "discord"] = "web"
    privacy: Literal["standard", "local_only"] = "standard"


class TurnCreate(BaseModel):
    request_id: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=20000)
    conversation_mode: Literal["text", "voice"] = "text"


def process(request_id: str) -> dict:
    if not store.claim(request_id):
        return store.result(request_id)
    row = store.load_turn(request_id)
    payload = json.loads(row["input_json"])
    try:
        with request_context.bind(request_id=request_id, session_id=row["thread_id"],
                                  conversation_mode=payload.get("conversation_mode", "text")):
            with lmstudio_client.observe_turn():
                attachment_ids = payload.get("attachment_ids") or []
                if attachment_ids:
                    from . import setup_store
                    settings = setup_store.load()
                    if settings["brain_enabled"] and settings.get("brain_transport") == "cli_only":
                        raise lmstudio_client.LMStudioError("CLIのみの画像付き会話は未対応です。画像を外して送信してください。SDK/APIへ自動送信しません。")
                    from . import attachments, brain_runtime, vision
                    brain.check_provider(store.thread(row["thread_id"]))
                    observations = vision.analyze(attachment_ids, row["thread_id"])
                    data = brain_runtime.run_with_images(payload["message"], observations,
                                                         history=store.history(row["thread_id"]))
                    # Observations retain their existing 24h TTL, not a second
                    # permanent copy in the request ledger.
                    data.get("model_route", {}).pop("vision", None)
                    result = store.finish(request_id, data)
                    attachments.save_observations(store.load_turn(request_id)["conversation_id"],
                                                 row["thread_id"], observations)
                    return result
                result = brain.run(request_id)
                if result["status"] == "completed" and store.thread(row["thread_id"])["privacy"] != "local_only":
                    from .chat import _artifact_executor, _persist_chat_artifacts
                    _artifact_executor.submit(_persist_chat_artifacts, store.load_turn(request_id)["conversation_id"],
                        payload["message"], result["reply"], ", ".join(t["name"] for t in result.get("used_tools", [])) or None)
                return result
    except brain.TurnCancelled as exc:
        return store.finish(request_id, {"reply": "", "error": str(exc)}, status="cancelled")
    except Exception as exc:
        log.warning("turn failed request_id=%s type=%s", request_id, type(exc).__name__)
        error = str(exc) if isinstance(exc, lmstudio_client.LMStudioError) else "会話処理に失敗しました。結果を照会してください。"
        return store.finish(request_id, {"reply": "", "error": error}, status="failed")


def submit(thread_id: str, request_id: str, message: str, *, source="web", conversation_mode="text",
           attachment_ids: list[str] | None = None, background=False) -> dict:
    store.create_thread(thread_id, source=source)
    row, created = store.accept(thread_id, request_id, {"message": message, "conversation_mode": conversation_mode,
                                                     "source": source,
                                                     "attachment_ids": attachment_ids or []})
    if created:
        if background:
            _executor.submit(process, request_id)
        else:
            return process(request_id)
    return store.result(request_id)


@router.post("/api/threads", status_code=201)
def create_thread(payload: ThreadCreate) -> dict:
    return store.create_thread(payload.id, source=payload.source, title=payload.title, privacy=payload.privacy)


@router.get("/api/threads")
def threads(limit: int = 30) -> dict:
    return {"threads": store.list_threads(limit)}


@router.get("/api/threads/{thread_id}/snapshot")
def snapshot(thread_id: str) -> dict:
    return store.snapshot(thread_id)


@router.get("/api/threads/{thread_id}/events")
def events(thread_id: str, after_seq: int = 0) -> dict:
    data = store.snapshot(thread_id, after_seq)
    return {"events": data["events"], "last_seq": data["events"][-1]["seq"] if data["events"] else after_seq}


@router.post("/api/threads/{thread_id}/turns", status_code=202)
def submit_turn(thread_id: str, payload: TurnCreate) -> dict:
    store.thread(thread_id)
    return submit(thread_id, payload.request_id, payload.message,
                  conversation_mode=payload.conversation_mode, background=True)


@router.get("/api/turns/{request_id}")
def get_turn(request_id: str) -> dict:
    return store.result(request_id)


@router.post("/api/turns/{request_id}/cancel")
def cancel_turn(request_id: str) -> dict:
    row = store.load_turn(request_id)
    with db.get_connection() as connection:
        connection.execute("UPDATE turns SET cancel_requested=1 WHERE request_id=?", (request_id,))
        if row["status"] in {"queued", "waiting_approval"}:
            connection.execute("UPDATE turns SET status='cancelled' WHERE request_id=?", (request_id,))
            connection.execute("UPDATE turn_approvals SET status='rejected' WHERE request_id=? AND status='pending'",
                               (request_id,))
        store.event(connection, row["thread_id"], request_id, "cancel_requested", {})
    return store.result(request_id)


def decide(approval_id: str, approved: bool) -> dict | None:
    item = store.approval(approval_id)
    if item is None:
        return None
    request_id = item["request_id"]
    row = store.load_turn(request_id)
    with db.write_transaction() as connection:
        current = connection.execute("SELECT * FROM turn_approvals WHERE id=?", (approval_id,)).fetchone()
        if current["status"] != "pending":
            return store.result(request_id)
        if current["expires_at"] < time.time():
            connection.execute("UPDATE turn_approvals SET status='expired' WHERE id=?", (approval_id,))
            return store.finish(request_id, {"reply": "", "error": "承認の期限が切れました。"}, status="cancelled")
        busy = connection.execute(
            "SELECT request_id FROM turns WHERE thread_id=? AND status IN ('queued','running')",
            (row["thread_id"],)).fetchone()
        if busy:
            raise HTTPException(429, {"error": "thread_busy", "request_id": busy["request_id"]})
        connection.execute("UPDATE turn_approvals SET status=? WHERE id=?",
                           ("approved" if approved else "rejected", approval_id))
        connection.execute("UPDATE turns SET status='running' WHERE request_id=?", (request_id,))
    call = {"id": item["call_id"], "function": {"name": item["tool"]}}
    arguments = json.loads(item["arguments_json"])
    try:
        with request_context.bind(request_id=request_id, session_id=row["thread_id"]):
            messages = json.loads(row["messages_json"] or "[]")
            raw = brain.execute(request_id, call, arguments) if approved else store.encode({"status": "cancelled_by_user"})
            # Replace only the matching pending result; retain every other call.
            for message in messages:
                if message.get("role") == "tool" and message.get("tool_call_id") == item["call_id"]:
                    message["content"] = brain.compact(raw, item["tool"])
            store.save_messages(request_id, messages)
            if store.approvals(request_id):
                with db.get_connection() as connection:
                    connection.execute("UPDATE turns SET status='waiting_approval' WHERE request_id=?", (request_id,))
                return store.result(request_id)
            return brain.run(request_id, messages=messages,
                             used_tools=json.loads(row["result_json"]).get("used_tools", []))
    except Exception as exc:
        error = str(exc) if isinstance(exc, lmstudio_client.LMStudioError) else "承認後の結果生成に失敗しました。操作結果を照会してください。"
        return store.finish(request_id, {"reply": "", "error": error}, status="failed")
