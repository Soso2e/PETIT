"""Internal confirmation wrapper that resumes the Agent after approved writes."""
from __future__ import annotations

import json
from typing import Any

from .. import agent_progress, agent_state
from .registry import dispatch, requires_confirmation, tool


def _failed(result: str) -> bool:
    if str(result or "").startswith("[error]"):
        return True
    try:
        value = json.loads(result)
    except (json.JSONDecodeError, TypeError):
        return False
    if not isinstance(value, dict):
        return False
    return bool(value.get("error")) or any(
        value.get(key) is False
        for key in ("ok", "created", "completed", "added", "saved", "updated")
    )


@tool(
    name="execute_agent_write",
    description=(
        "PETIT内部専用。確認済みの書き込みToolを実行し、保存済みAgent状態から最終返答を再開する。"
        "LLMは直接呼び出さない。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "resume_id": {"type": "string"},
            "tool_name": {"type": "string"},
            "tool_arguments": {"type": "object"},
        },
        "required": ["resume_id", "tool_name", "tool_arguments"],
    },
)
def execute_agent_write(
    resume_id: str,
    tool_name: str,
    tool_arguments: dict[str, Any],
) -> str | dict[str, Any]:
    state = agent_state.load(resume_id)
    if state is None:
        return {"ok": False, "error": "Agentの再開状態が見つからないか、期限切れです。"}

    target = str(tool_name or "").strip()
    if target == "execute_agent_write" or not requires_confirmation(target):
        return {"ok": False, "error": "確認対象として許可されていないToolです。", "tool": target}

    request_id = state.get("request_id")
    session_id = state.get("session_id")
    agent_progress.emit(
        "tool_started",
        "確認された内容を書き込んでるよ",
        tool=target,
        details={"arguments": tool_arguments},
        request_id=request_id,
        session_id=session_id,
    )
    raw_result = dispatch(target, tool_arguments)
    if _failed(raw_result):
        agent_progress.emit(
            "tool_finished",
            "書き込みに失敗したよ",
            tool=target,
            details={"ok": False},
            request_id=request_id,
            session_id=session_id,
        )
        return {"ok": False, "error": raw_result, "tool": target}

    try:
        from .. import agent_runtime  # Lazy import avoids tool-registration cycles.

        reply = agent_runtime.resume_after_write(state, target, tool_arguments, raw_result)
    finally:
        agent_state.delete(resume_id)
    return reply or "確認された内容を実行したよ。"
