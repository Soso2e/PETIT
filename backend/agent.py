"""PETIT conversation entrypoint backed by one PETIT Brain and bounded runtimes.

Project continuity, named task completion and exact current-time reads stay
deterministic. Ordinary conversation enters the PETIT Brain, which can answer in
one call, request bounded read context, or delegate complex/action work to the
existing Agent runtime.
"""
from __future__ import annotations

from typing import Any

from . import agent_legacy as _legacy
from . import agent_runtime, brain_runtime, capability_router, config, project_router, task_completion_intent
from .petit_prompt import CORE_SYSTEM_PROMPT

for _export_name in dir(_legacy):
    if not _export_name.startswith("__"):
        globals()[_export_name] = getattr(_legacy, _export_name)

model_router = capability_router

_COMPAT_TASK_SIGNALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "update_task",
        (
            "タスクを編集", "タスクを変更", "タスク名を変更", "期限を変更",
            "優先度を変更", "締切を延ば", "日付を変", "未完了に戻",
        ),
    ),
    (
        "retry_task_sync",
        ("タスク同期を再試行", "Notion同期を再試行", "同期をやり直"),
    ),
    (
        "get_task_sync_status",
        ("タスク同期状態", "タスクの同期状況", "同期エラー", "同期の失敗理由"),
    ),
)
_existing_signal_names = {name for name, _signals in _TOOL_SIGNALS}
_TOOL_SIGNALS = tuple(_TOOL_SIGNALS) + tuple(
    item for item in _COMPAT_TASK_SIGNALS if item[0] not in _existing_signal_names
)
_legacy._TOOL_SIGNALS = _TOOL_SIGNALS

CHAT_SYSTEM_PROMPT = CORE_SYSTEM_PROMPT
AGENT_SYSTEM_PROMPT = CORE_SYSTEM_PROMPT
SYSTEM_PROMPT = CORE_SYSTEM_PROMPT
_legacy.CHAT_SYSTEM_PROMPT = CHAT_SYSTEM_PROMPT
_legacy.AGENT_SYSTEM_PROMPT = AGENT_SYSTEM_PROMPT
_legacy.SYSTEM_PROMPT = SYSTEM_PROMPT

_RUNTIME_AGENT_BASE_PROMPT = CORE_SYSTEM_PROMPT
agent_runtime._AGENT_SYSTEM_PROMPT = _RUNTIME_AGENT_BASE_PROMPT


def _refresh_runtime_time_context() -> None:
    """Keep the shared PETIT system prefix static."""
    agent_runtime._AGENT_SYSTEM_PROMPT = _RUNTIME_AGENT_BASE_PROMPT


def _sync_legacy_globals() -> None:
    """Propagate monkey-patched dependencies used by compatibility tests."""
    for name in (
        "config", "db", "project_router", "recall", "situation", "tools",
        "chat_completion", "parse_schedule_date", "has_schedule_date_expression", "_TOOL_SIGNALS",
    ):
        if name in globals():
            setattr(_legacy, name, globals()[name])
    agent_runtime.chat_completion = globals()["chat_completion"]
    brain_runtime.chat_completion = globals()["chat_completion"]
    capability_router.chat_completion = globals()["chat_completion"]
    agent_runtime.tools = globals()["tools"]
    agent_runtime.capability_router = model_router


def _notion_read_requested(message: str) -> bool:
    text = str(message or "").casefold()
    return any(marker in text for marker in ("notion", "ノーション"))


def _github_review_requested(message: str) -> bool:
    text = str(message or "").casefold()
    return any(marker in text for marker in ("github", "ギットハブ"))


def _related_tool_names(message: str) -> list[str]:
    """Legacy introspection only; the live route uses the PETIT Brain."""
    _legacy._TOOL_SIGNALS = _TOOL_SIGNALS
    return list(_legacy._related_tool_names(message))


def _run_notion_read(user_message: str, history: list[dict[str, str]] | None) -> dict[str, Any]:
    _refresh_runtime_time_context()
    return brain_runtime.run(user_message, history=history)


def _run_github_review(user_message: str) -> dict[str, Any]:
    _refresh_runtime_time_context()
    return brain_runtime.run(user_message, history=None)


def run(
    user_message: str,
    history: list[dict[str, str]] | None = None,
    *,
    allow_defer: bool = True,
) -> dict[str, Any]:
    """Handle one turn through deterministic safety gates, then the PETIT Brain."""
    del allow_defer
    _refresh_runtime_time_context()
    _sync_legacy_globals()
    recent_history = _legacy._recent_history(history)

    task_completion_turn = task_completion_intent.try_handle(user_message)
    if task_completion_turn:
        return task_completion_turn

    project_turn = project_router.try_handle_project_turn(
        user_message,
        user_id=config.PETIT_OWNER_ID,
        recent_history=recent_history,
    )
    if project_turn:
        return project_turn

    if _legacy._related_tool_names(user_message) == ["get_current_time"]:
        raw = tools.dispatch("get_current_time", {})
        direct = _legacy._format_direct_time(raw)
        if direct:
            return {
                "reply": direct,
                "used_tools": [{"name": "get_current_time", "arguments": "{}"}],
                "model_route": {
                    "kind": "direct",
                    "requested_route": "deterministic",
                    "actual_route": "deterministic",
                    "model": None,
                    "tools": ["get_current_time"],
                    "reasons": ["deterministic_current_time"],
                    "llm_call_count": 0,
                },
            }

    return brain_runtime.run(user_message, history=recent_history)


__all__ = [
    "run", "CHAT_SYSTEM_PROMPT", "AGENT_SYSTEM_PROMPT", "SYSTEM_PROMPT", "capability_router",
]
