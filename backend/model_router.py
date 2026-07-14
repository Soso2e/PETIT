"""Deterministic routing between PETIT's chat and agent models."""
from __future__ import annotations

from typing import Any

from . import config

_AGENT_SIGNALS = (
    "タスク", "予定", "カレンダー", "notion", "brain", "記憶", "覚えて",
    "調べ", "検索", "ニュース", "天気", "ツール", "同期", "実装", "修正",
    "分析", "比較", "設計", "計画", "優先", "今週", "明日", "今日何", "何すれば",
    "どこまで", "続き", "まとめ", "プロジェクト", "決定", "方針",
    "今何時", "今日何日", "現在時刻", "完了", "終わった", "中断", "復帰",
)

def choose(
    user_message: str,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the selected model plus transparent routing reasons."""
    text = user_message.strip()
    reasons: list[str] = []
    lowered = text.casefold()
    if any(signal.casefold() in lowered for signal in _AGENT_SIGNALS):
        reasons.append("tools_or_reasoning")
    if text.count("\n") >= 4 or sum(text.count(mark) for mark in ("、", "。", "* ", "- ")) >= 8:
        reasons.append("multi_part")

    use_agent = bool(reasons)
    return {
        "kind": "agent" if use_agent else "chat",
        "model": config.AGENT_MODEL if use_agent else config.CHAT_MODEL,
        "reasons": reasons or ["simple_conversation"],
    }


def can_defer(user_message: str, route: dict[str, Any]) -> bool:
    """Deferred chat turns were removed; keep this compatibility helper false."""
    del user_message, route
    return False
