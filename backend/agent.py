"""PETIT conversation entrypoint backed by the contextual bounded Agent runtime.

The legacy module remains re-exported for compatibility with existing tests and
callers. Project continuity and instant greetings stay deterministic; normal
conversation, reads, and writes are interpreted from context by the LLM runtime.
"""
from __future__ import annotations

from typing import Any

from . import agent_legacy as _legacy
from . import agent_runtime, capability_router, config, project_router

# Re-export the historical module surface while the runtime migration stabilizes.
for _export_name in dir(_legacy):
    if not _export_name.startswith("__"):
        globals()[_export_name] = getattr(_legacy, _export_name)

CHAT_SYSTEM_PROMPT = (
    "あなたはPETIT。親しみやすく、柔らかく自然な日本語で直接答える。"
    "Markdownは使わない。"
)
AGENT_SYSTEM_PROMPT = (
    "あなたはPETIT。会話文脈から目的を理解し、必要なToolだけを使う。"
    "Tool結果を踏まえて目的を満たしたか判断し、書き込みは確認なしに実行しない。"
    "Markdownは使わない。"
)
SYSTEM_PROMPT = AGENT_SYSTEM_PROMPT
_legacy.CHAT_SYSTEM_PROMPT = CHAT_SYSTEM_PROMPT
_legacy.AGENT_SYSTEM_PROMPT = AGENT_SYSTEM_PROMPT
_legacy.SYSTEM_PROMPT = SYSTEM_PROMPT


def _sync_legacy_globals() -> None:
    """Propagate monkey-patched dependencies used by compatibility tests."""
    for name in (
        "config",
        "db",
        "model_router",
        "project_router",
        "recall",
        "situation",
        "tools",
        "chat_completion",
        "parse_schedule_date",
        "has_schedule_date_expression",
        "_TOOL_SIGNALS",
    ):
        if name in globals():
            setattr(_legacy, name, globals()[name])


# Compatibility helpers retained for callers that inspect the old routing layer.
def _notion_read_requested(message: str) -> bool:
    text = str(message or "").casefold()
    return any(marker in text for marker in ("notion", "ノーション"))


def _github_review_requested(message: str) -> bool:
    text = str(message or "").casefold()
    return any(marker in text for marker in ("github", "ギットハブ"))


def _related_tool_names(message: str) -> list[str]:
    """Legacy introspection only; the live route uses Capability Router."""
    return list(_legacy._related_tool_names(message))


def _run_notion_read(user_message: str, history: list[dict[str, str]] | None) -> dict[str, Any]:
    return agent_runtime.run(user_message, history=history)


def _run_github_review(user_message: str) -> dict[str, Any]:
    return agent_runtime.run(user_message, history=None)


def run(
    user_message: str,
    history: list[dict[str, str]] | None = None,
    *,
    allow_defer: bool = True,
) -> dict[str, Any]:
    """Handle one turn through deterministic safety gates then the LLM Agent."""
    del allow_defer
    _sync_legacy_globals()
    recent_history = _legacy._recent_history(history)

    project_turn = project_router.try_handle_project_turn(
        user_message,
        user_id=config.PETIT_OWNER_ID,
        recent_history=recent_history,
    )
    if project_turn:
        return project_turn

    instant = _legacy._instant_reply(user_message)
    if instant:
        return instant

    return agent_runtime.run(user_message, history=recent_history)


__all__ = [
    "run",
    "CHAT_SYSTEM_PROMPT",
    "AGENT_SYSTEM_PROMPT",
    "SYSTEM_PROMPT",
    "capability_router",
]
