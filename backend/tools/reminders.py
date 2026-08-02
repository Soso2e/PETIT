"""Conversation tools for PETIT reminders."""
from __future__ import annotations

from typing import Any

from .. import reminders
from .registry import tool


@tool(
    name="create_reminder",
    description=(
        "指定日時または指定分後に、PETITから通知する単発リマインダーを作成する。"
        "『30分後にカフェへ行く時間だと知らせて』ではdelay_minutes=30を使う。"
        "『2026年8月5日14時に提出を知らせて』ではtrigger_atをISO日時で指定する。"
        "trigger_atとdelay_minutesは同時に指定しない。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "一覧と通知に表示する短いタイトル"},
            "trigger_at": {
                "type": "string",
                "description": "通知日時。ISO 8601。時差なしの場合はPETIT_TIMEZONE（既定Asia/Tokyo）として扱う。",
            },
            "delay_minutes": {
                "type": "integer",
                "description": "現在から何分後に通知するか。相対指定で使う。",
                "minimum": 1,
            },
            "message": {"type": "string", "description": "通知本文。省略時はタイトルから生成。"},
            "related_task_id": {"type": "integer", "description": "関連するPETITタスクID。任意。"},
            "source_message": {"type": "string", "description": "ユーザーの元の依頼文。任意。"},
        },
        "required": ["title"],
    },
    requires_confirmation=True,
)
def create_reminder(
    title: str,
    trigger_at: str | None = None,
    delay_minutes: int | None = None,
    message: str | None = None,
    related_task_id: int | None = None,
    source_message: str | None = None,
) -> dict[str, Any]:
    try:
        item = reminders.create_reminder(
            title=title,
            trigger_at=trigger_at,
            delay_minutes=delay_minutes,
            message=message,
            related_task_id=related_task_id,
            source_message=source_message,
        )
    except ValueError as exc:
        return {"created": False, "error": str(exc)}
    return {
        "created": True,
        "reminder": item,
        "message": f"{item['trigger_at']}に『{item['title']}』をリマインドします。",
    }


@tool(
    name="get_reminders",
    description=(
        "PETITに登録済みのリマインダーを取得する。"
        "scopeはupcoming（未完了）、history（完了・取消）、all。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "scope": {
                "type": "string",
                "enum": ["upcoming", "history", "all"],
                "default": "upcoming",
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
        },
    },
)
def get_reminders(scope: str = "upcoming", limit: int = 50) -> dict[str, Any]:
    try:
        return reminders.list_reminders(scope=scope, limit=limit)
    except ValueError as exc:
        return {"count": 0, "items": [], "error": str(exc)}


@tool(
    name="manage_reminder",
    description=(
        "登録済みリマインダーを完了、取消、または指定分後へ延期する。"
        "actionはcomplete、cancel、snooze。snooze時だけminutesを使う。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "reminder_id": {"type": "integer", "description": "対象リマインダーID"},
            "action": {"type": "string", "enum": ["complete", "cancel", "snooze"]},
            "minutes": {"type": "integer", "minimum": 1, "maximum": 10080, "default": 10},
        },
        "required": ["reminder_id", "action"],
    },
    requires_confirmation=True,
)
def manage_reminder(reminder_id: int, action: str, minutes: int = 10) -> dict[str, Any]:
    try:
        if action == "complete":
            return reminders.complete_reminder(reminder_id)
        if action == "cancel":
            return reminders.cancel_reminder(reminder_id)
        if action == "snooze":
            return reminders.snooze_reminder(reminder_id, minutes)
        return {"updated": False, "error": "Unsupported action"}
    except ValueError as exc:
        return {"updated": False, "error": str(exc)}
