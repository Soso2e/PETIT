"""Conversation tools for Discord-only channel reminders (Owner mode)."""
from __future__ import annotations

from typing import Any

from .. import discord_api, discord_reminders, request_context
from .registry import tool


def _current_discord_channel() -> str | None:
    _, session_id = request_context.current_ids()
    if session_id and session_id.startswith("discord:"):
        ch = session_id.removeprefix("discord:").strip()
        if ch.isdigit():
            return ch
    return None


@tool(
    name="create_discord_reminder",
    description=(
        "Discordの現在のチャンネル宛に指定日時でリマインダーを登録する（Discord専用・即時登録）。"
        "Discord上での「〇日に通知して」「リマインドして」の依頼では、個人用create_reminderではなく必ずこのToolを使う。"
        "日付のみ（例: 2026-12-01）が指定され時刻が省略された場合は朝09:00に通知される。"
        "メンション先 mention_target は指定がなければ 'user'（話しかけた本人）、全員・everyone指定時は 'everyone' を使う。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "リマインドする内容・件名（例: 定例MTG、ゴミ出し、提出期限）",
            },
            "trigger_at": {
                "type": "string",
                "description": "通知日時。YYYY-MM-DD（09:00扱い）または ISO 8601 日時（例: 2026-12-01T15:00:00+09:00）。",
            },
            "delay_minutes": {
                "type": "integer",
                "description": "現在から何分後に通知するか（相対指定用）。trigger_atと同時指定しない。",
                "minimum": 1,
            },
            "message": {
                "type": "string",
                "description": "通知本文。省略時はtitleが使われる。",
            },
            "mention_target": {
                "type": "string",
                "enum": ["user", "everyone"],
                "default": "user",
                "description": "通知時のメンション先。指定がなければ 'user'（本人）。全員宛なら 'everyone'。",
            },
        },
        "required": ["title"],
    },
    requires_confirmation=False,
)
def create_discord_reminder(
    title: str,
    trigger_at: str | None = None,
    delay_minutes: int | None = None,
    message: str | None = None,
    mention_target: str = "user",
) -> dict[str, Any]:
    channel_id = _current_discord_channel()
    if not channel_id:
        return {
            "created": False,
            "error": "Discordチャンネルの会話ではないため登録できません。個人リマインダーには create_reminder を使ってください。",
        }
    author_id = request_context.current_discord_author_id() or discord_api.owner_id()
    if not author_id:
        return {"created": False, "error": "発信者のDiscordユーザーIDが特定できませんでした。"}
    guild_id = request_context.current_discord_guild_id()
    try:
        item = discord_reminders.create_owner_reminder(
            channel_id=channel_id,
            author_id=author_id,
            title=title,
            trigger_at=trigger_at,
            delay_minutes=delay_minutes,
            message=message,
            mention_target=mention_target,
            guild_id=guild_id,
        )
    except ValueError as exc:
        return {"created": False, "error": str(exc)}
    mention_label = "@everyone" if item["mention_target"] == "everyone" else f"<@{item['author_id']}>"
    return {
        "created": True,
        "reminder": item,
        "message": f"{item['trigger_at_local']} にこのチャンネル（<#{channel_id}>）へ {mention_label} 宛で『{item['title']}』をリマインドします。",
    }


@tool(
    name="list_discord_reminders",
    description="Discordチャンネル専用リマインダーの予定一覧を取得する。",
    parameters={
        "type": "object",
        "properties": {
            "channel_only": {
                "type": "boolean",
                "default": True,
                "description": "Trueなら現在のチャンネルのみ、Falseなら全Discordチャンネルを取得。",
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
        },
    },
)
def list_discord_reminders(channel_only: bool = True, limit: int = 20) -> dict[str, Any]:
    channel_id = _current_discord_channel() if channel_only else None
    items = discord_reminders.list_owner_reminders(channel_id=channel_id, limit=limit)
    return {"count": len(items), "items": items}


@tool(
    name="cancel_discord_reminder",
    description="登録済みのDiscordチャンネル専用リマインダーをキャンセルする。",
    parameters={
        "type": "object",
        "properties": {
            "reminder_id": {"type": "integer", "description": "キャンセルするリマインダーID"},
        },
        "required": ["reminder_id"],
    },
    requires_confirmation=False,
)
def cancel_discord_reminder(reminder_id: int) -> dict[str, Any]:
    channel_id = _current_discord_channel()
    try:
        item = discord_reminders.cancel_owner_reminder(reminder_id, channel_id=channel_id)
    except ValueError as exc:
        return {"cancelled": False, "error": str(exc)}
    return {"cancelled": True, "reminder": item}
