"""Discord channel adapter on the Core side (D1: Owner mode).

The Bot process only relays events. Core alone decides who the owner is, so a
compromised or misconfigured Bot cannot widen access: anything that is not the
owner in a DM or an owner-designated guild gets a fixed guide and no Brain call.
"""
from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from . import conversation_api, conversation_store as store

router = APIRouter()

GUEST_GUIDE = ("こんにちは、プティです。このサーバーではまだ使えません。"
               "サーバー向けのモード（タスク・予定・リマインド）は準備中です。")
APPROVAL_NOTE = "確認が必要な操作があります。いまは PETIT の画面（Web / Desktop）で承認してください。"


class DiscordEvent(BaseModel):
    event_id: str = Field(min_length=1, max_length=40, pattern=r"^[0-9]+$")
    channel_id: str = Field(min_length=1, max_length=40, pattern=r"^[0-9]+$")
    guild_id: str | None = Field(default=None, max_length=40, pattern=r"^[0-9]+$")
    author_id: str = Field(min_length=1, max_length=40, pattern=r"^[0-9]+$")
    message: str = Field(min_length=1, max_length=20000)


def owner_id() -> str:
    return os.getenv("PETIT_DISCORD_OWNER_ID", "").strip()


def owner_guild_ids() -> set[str]:
    return {x.strip() for x in os.getenv("PETIT_DISCORD_OWNER_GUILD_IDS", "").split(",") if x.strip()}


def mode_for(event: DiscordEvent) -> str:
    owner = owner_id()
    if not owner or not hmac.compare_digest(event.author_id, owner):
        return "guest"
    if event.guild_id is None or event.guild_id in owner_guild_ids():
        return "owner"
    # The owner speaking in an undesignated guild still gets no personal data.
    return "guest"


def _authorize(authorization: str | None) -> None:
    expected = os.getenv("PETIT_DISCORD_SERVICE_TOKEN", "")
    if len(expected) < 32:
        raise HTTPException(503, "Discord連携は設定されていません。")
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(401, "認証できませんでした。")


def _reply(result: dict) -> dict:
    status = result.get("status")
    text = str(result.get("reply") or "")
    if status == "waiting_approval":
        text = (text + "\n\n" if text else "") + APPROVAL_NOTE
    elif status in {"failed", "cancelled"}:
        text = result.get("error") or "うまく処理できませんでした。"
    return {"mode": "owner", "status": status, "reply": text, "request_id": result.get("request_id")}


@router.post("/api/channels/discord/events")
def receive(event: DiscordEvent, authorization: str | None = Header(default=None)) -> dict:
    _authorize(authorization)
    if mode_for(event) != "owner":
        return {"mode": "guest", "status": "completed", "reply": GUEST_GUIDE}
    # One Core Thread per Discord channel / thread; the message ID is the request ID,
    # so a redelivered gateway event returns the saved result instead of re-running.
    thread_id = "discord:" + event.channel_id
    request_id = "discord:" + event.event_id
    result = conversation_api.submit(thread_id, request_id, event.message, source="discord", is_admin=True)
    return _reply({**result, "request_id": request_id})


@router.get("/api/channels/discord/events/{event_id}")
def result(event_id: str, authorization: str | None = Header(default=None)) -> dict:
    _authorize(authorization)
    if not event_id.isdigit():
        raise HTTPException(400, "event_id が不正です。")
    request_id = "discord:" + event_id
    return _reply({**store.result(request_id), "request_id": request_id})
