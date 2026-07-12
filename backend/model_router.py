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

_DEFERABLE_SIGNALS = (
    "今日何", "何すれば", "予定", "カレンダー", "タスク", "notion", "brain",
    "記憶", "検索", "調べ", "ニュース", "天気", "分析", "比較", "優先",
    "どこまで", "続き", "復帰", "まとめ", "プロジェクト", "方針",
)

_IMMEDIATE_ACTION_SIGNALS = (
    "覚えて", "保存", "タスクにして", "追加して", "作って", "登録して",
    "完了", "終わった", "消して", "削除", "更新して", "同期して",
    "今何時", "今日何日", "現在時刻",
)


def choose(
    user_message: str,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the selected model plus transparent routing reasons."""
    text = user_message.strip()
    history_chars = sum(len(str(item.get("content", ""))) for item in (history or []))
    reasons: list[str] = []
    if len(text) >= config.AGENT_MESSAGE_CHARS:
        reasons.append("long_request")
    if history_chars >= config.AGENT_HISTORY_CHARS:
        reasons.append("long_context")
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
    """Whether this agent turn can safely run as a follow-up job."""
    if route.get("kind") != "agent":
        return False
    text = user_message.strip().casefold()
    if not text:
        return False
    if any(signal.casefold() in text for signal in _IMMEDIATE_ACTION_SIGNALS):
        return False
    return any(signal.casefold() in text for signal in _DEFERABLE_SIGNALS)
