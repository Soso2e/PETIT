"""Discord channel adapter on the Core side (D1: Owner mode).

The Bot process only relays events. Core alone decides who the owner is, so a
compromised or misconfigured Bot cannot widen access: anything that is not the
owner in a DM or an owner-designated guild gets a fixed guide and no Brain call.
"""
from __future__ import annotations

import hmac
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from . import conversation_api, conversation_store as store, db

router = APIRouter()

GUEST_GUIDE = ("こんにちは、プティです。このサーバーではまだ使えません。"
               "サーバー向けのモード（タスク・予定・リマインド）は準備中です。")
APPROVAL_NOTE = "確認が必要な操作があります。下のボタンか PETIT の画面で承認してください。"
PREVIEW_CHARS = 1500
NOTIFY_WINDOW = timedelta(hours=1)


class DiscordEvent(BaseModel):
    event_id: str = Field(min_length=1, max_length=40, pattern=r"^[0-9]+$")
    channel_id: str = Field(min_length=1, max_length=40, pattern=r"^[0-9]+$")
    guild_id: str | None = Field(default=None, max_length=40, pattern=r"^[0-9]+$")
    author_id: str = Field(min_length=1, max_length=40, pattern=r"^[0-9]+$")
    display_name: str = Field(default="", max_length=120)
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


def _approvals(result: dict) -> list[dict]:
    items = []
    for action in result.get("pending_actions") or []:
        preview = action.get("preview") or store.encode(action.get("arguments") or {})
        items.append({"approval_id": action["approval_id"], "name": action["name"],
                      "preview": preview[:PREVIEW_CHARS] + ("…" if len(preview) > PREVIEW_CHARS else "")})
    return items


def _reply(result: dict) -> dict:
    status = result.get("status")
    text = str(result.get("reply") or "")
    if status == "waiting_approval":
        text = (text + "\n\n" if text else "") + APPROVAL_NOTE
    elif status in {"failed", "cancelled"}:
        text = result.get("error") or "うまく処理できませんでした。"
    return {"mode": "owner", "status": status, "reply": text, "request_id": result.get("request_id"),
            "approvals": _approvals(result) if status == "waiting_approval" else []}


@router.post("/api/channels/discord/events")
def receive(event: DiscordEvent, authorization: str | None = Header(default=None)) -> dict:
    _authorize(authorization)
    if mode_for(event) != "owner":
        if event.guild_id is not None:
            from . import guild_api
            if guild_api.is_configured(event.guild_id):
                return guild_api.handle_mention(
                    guild_api.GuildMessageRequest(
                        event_id=event.event_id,
                        guild_id=event.guild_id,
                        channel_id=event.channel_id,
                        author_id=event.author_id,
                        display_name=event.display_name,
                        message=event.message,
                    )
                )
        return {"mode": "guest", "status": "completed", "reply": GUEST_GUIDE, "approvals": []}
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


class ApprovalDecision(BaseModel):
    interaction_id: str = Field(min_length=1, max_length=40, pattern=r"^[0-9]+$")
    approval_id: str = Field(min_length=1, max_length=64, pattern=r"^[0-9a-f]+$")
    guild_id: str | None = Field(default=None, max_length=40, pattern=r"^[0-9]+$")
    author_id: str = Field(min_length=1, max_length=40, pattern=r"^[0-9]+$")
    approved: bool


@router.post("/api/channels/discord/approvals")
def decide(body: ApprovalDecision, authorization: str | None = Header(default=None)) -> dict:
    _authorize(authorization)
    probe = DiscordEvent(event_id=body.interaction_id, channel_id="0", guild_id=body.guild_id,
                         author_id=body.author_id, message="-")
    if mode_for(probe) != "owner":
        raise HTTPException(403, "このボタンは PETIT の持ち主だけが押せます。")
    item = store.approval(body.approval_id)
    # Discord may only decide what Discord asked for; Web/Desktop approvals stay there.
    if item is None or not str(item["request_id"]).startswith("discord:"):
        raise HTTPException(404, "承認が見つかりません。")
    result = conversation_api.decide(body.approval_id, body.approved)
    if result is None:
        raise HTTPException(404, "承認が見つかりません。")
    return _reply({**result, "request_id": item["request_id"]})


def notifications_enabled() -> bool:
    return os.getenv("PETIT_DISCORD_NOTIFICATIONS", "").strip().lower() in {"1", "on", "true", "yes"}


@router.get("/api/channels/discord/notifications")
def claim_notifications(limit: int = Query(default=10, ge=1, le=20),
                        authorization: str | None = Header(default=None)) -> dict:
    """Claim recent, user-enabled notification events for one Discord DM each.

    A claim is recorded before delivery, so a crash between claim and send leaves
    the event as 'claimed' (unknown) and it is never re-sent automatically.
    """
    _authorize(authorization)
    if not notifications_enabled() or not owner_id():
        return {"owner_id": None, "notifications": []}
    from . import notifications
    notifications.init_db()
    enabled = {k for k, v in notifications.get_preferences().items() if v}
    if not enabled:
        return {"owner_id": owner_id(), "notifications": []}
    cutoff = (datetime.now(timezone.utc) - NOTIFY_WINDOW).isoformat(timespec="seconds")
    marks = ",".join("?" for _ in enabled)
    claimed = []
    with db.write_transaction() as connection:
        rows = connection.execute(
            f"SELECT id,category,title,body FROM notification_events e WHERE created_at>=? AND category IN ({marks}) "
            "AND NOT EXISTS (SELECT 1 FROM notification_deliveries d WHERE d.event_id=e.id AND d.provider='discord') "
            "ORDER BY id LIMIT ?", (cutoff, *sorted(enabled), limit)).fetchall()
        now = db.now_iso()
        for row in rows:
            connection.execute("INSERT INTO notification_deliveries(event_id,provider,status,created_at) "
                               "VALUES(?,?,?,?)", (row["id"], "discord", "claimed", now))
            claimed.append({"event_id": row["id"], "category": row["category"], "title": row["title"], "body": row["body"]})
    return {"owner_id": owner_id(), "notifications": claimed}


class DeliveryReport(BaseModel):
    status: str = Field(pattern=r"^(sent|failed)$")
    error: str | None = Field(default=None, max_length=500)


@router.post("/api/channels/discord/notifications/{event_id}")
def report_notification(event_id: int, body: DeliveryReport, authorization: str | None = Header(default=None)) -> dict:
    _authorize(authorization)
    with db.get_connection() as connection:
        updated = connection.execute(
            "UPDATE notification_deliveries SET status=?, error=?, sent_at=? "
            "WHERE event_id=? AND provider='discord' AND status='claimed'",
            (body.status, body.error, db.now_iso() if body.status == "sent" else None, event_id)).rowcount
    if not updated:
        raise HTTPException(404, "確保済みの通知がありません。")
    return {"event_id": event_id, "status": body.status}
