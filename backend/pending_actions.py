"""Pending write approval state and confirmation API."""
from __future__ import annotations

import json
import threading
import time
from typing import Any
from uuid import uuid4

from fastapi import APIRouter

from . import config, tools
from .chat_models import ActionDecision, ChatResponse, PendingAction

router = APIRouter()

_pending_actions: dict[str, dict[str, Any]] = {}
_pending_actions_lock = threading.Lock()
_PENDING_ACTION_TTL_SECONDS = 600


def register(actions: list[dict[str, Any]]) -> list[PendingAction]:
    now = time.monotonic()
    registered: list[PendingAction] = []
    with _pending_actions_lock:
        expired = [key for key, value in _pending_actions.items() if now - value["created_at"] > _PENDING_ACTION_TTL_SECONDS]
        for key in expired:
            _pending_actions.pop(key, None)
        for action in actions:
            action_name = str(action["name"])
            action_arguments = dict(action.get("arguments") or {})
            if config.USE_SONA_CORE and action_name == "add_schedule":
                from . import sona_core_add_schedule

                approval_id = sona_core_add_schedule.register_pending(action_arguments)
                registered.append(PendingAction(approval_id=approval_id, name=action_name, arguments=action_arguments))
                continue
            approval_id = uuid4().hex
            value = {
                "name": action_name,
                "arguments": action_arguments,
                "created_at": now,
            }
            _pending_actions[approval_id] = value
            registered.append(PendingAction(approval_id=approval_id, name=value["name"], arguments=value["arguments"]))
    return registered


@router.post("/api/actions/{approval_id}", response_model=ChatResponse)
def decide_action(approval_id: str, decision: ActionDecision) -> ChatResponse:
    if config.USE_SONA_CORE:
        try:
            from . import sona_core_add_schedule

            core_request = sona_core_add_schedule.get_pending(approval_id)
        except Exception:  # noqa: BLE001
            core_request = None
        if core_request is not None and core_request.invocation.call.name == "add_schedule":
            try:
                result = sona_core_add_schedule.decide_pending(approval_id, decision.approved)
            except (KeyError, ValueError) as exc:
                return ChatResponse(reply="", error=f"確認操作を実行できません。{exc}")
            if not decision.approved:
                return ChatResponse(reply="書き込みをキャンセルしました。")
            if result is None or result.status != "success":
                message = result.error.message if result and result.error else "schedule write failed"
                return ChatResponse(reply="", error=f"書き込みに失敗しました。{message}")
            rendered = json.dumps(result.data, ensure_ascii=False, default=str)
            return ChatResponse(
                reply=f"確認された内容を実行しました。\n{_short_tool_result(rendered)}",
                used_tools=[{"name": "add_schedule", "arguments": core_request.invocation.call.arguments}],
            )

    with _pending_actions_lock:
        action = _pending_actions.pop(approval_id, None)
    if action is None or time.monotonic() - action["created_at"] > _PENDING_ACTION_TTL_SECONDS:
        return ChatResponse(reply="", error="確認待ち操作が見つからないか、期限切れです。")
    if not decision.approved:
        return ChatResponse(reply="書き込みをキャンセルしました。")

    result = tools.dispatch(action["name"], action["arguments"])
    if _tool_result_failed(result):
        return ChatResponse(reply="", error=f"書き込みに失敗しました。{_short_tool_result(result)}")
    return ChatResponse(
        reply=_confirmed_action_reply(action["name"], result),
        used_tools=[{"name": action["name"], "arguments": action["arguments"]}],
    )


def _tool_result_failed(result: str) -> bool:
    if result.startswith("[error]"):
        return True
    try:
        data = json.loads(result)
    except json.JSONDecodeError:
        return False
    return isinstance(data, dict) and (
        bool(data.get("error"))
        or any(data.get(key) is False for key in ("ok", "created", "completed", "added", "saved", "updated"))
    )


def _short_tool_result(result: str) -> str:
    return result if len(result) <= 600 else result[:600] + "…"


def _confirmed_action_reply(action_name: str, result: str) -> str:
    if action_name == "complete_task":
        try:
            data = json.loads(result)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict) and data.get("completed"):
            task = data.get("task") if isinstance(data.get("task"), dict) else {}
            title = str(task.get("title") or "タスク")
            return f"「{title}」を完了にしたよ。おつかれさま！"
    return f"確認された内容を実行しました。\n{_short_tool_result(result)}"
