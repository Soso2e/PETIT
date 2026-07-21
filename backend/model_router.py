"""Deterministic routing between PETIT's chat and agent models."""
from __future__ import annotations

from typing import Any

from . import config

# Tool requests are routed separately in ``agent.py``. This router only decides
# whether a tool-free turn needs the stronger reasoning model. Keep the signals
# phrase-based so casual lines such as 「問題ないよ」 or 「今日は改善した」 stay
# in the fast, natural chat path.
_AGENT_PHRASES = (
    "原因を教えて",
    "原因を考えて",
    "問題を分析",
    "問題点を",
    "改善案",
    "改善方法",
    "どう改善",
    "比較して",
    "違いを比較",
    "設計して",
    "設計を考えて",
    "計画を立て",
    "優先順位",
    "レビューして",
    "検証して",
    "デバッグして",
    "実装して",
    "修正して",
    "要件を整理",
    "仕様を整理",
    "なぜ",
    "どうして",
)

_REASONING_DOMAINS = (
    "コード",
    "実装",
    "設計",
    "仕様",
    "要件",
    "アーキテクチャ",
    "プロジェクト",
    "モデル",
    "ai",
    "エージェント",
)

_REASONING_ACTIONS = (
    "考えて",
    "分析して",
    "評価して",
    "整理して",
    "提案して",
    "見直して",
    "レビューして",
    "比較して",
)


def choose(
    user_message: str,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the selected model plus transparent routing reasons.

    Tool selection remains separate. This router catches only tool-free reasoning
    turns such as code review or architecture analysis without promoting ordinary
    conversation merely because it contains a broad word like ``問題``.
    """
    del history  # Reserved for future conversation-aware routing.
    text = user_message.strip()
    reasons: list[str] = []
    lowered = text.casefold()

    if any(phrase.casefold() in lowered for phrase in _AGENT_PHRASES):
        reasons.append("explicit_reasoning")
    elif (
        any(domain.casefold() in lowered for domain in _REASONING_DOMAINS)
        and any(action.casefold() in lowered for action in _REASONING_ACTIONS)
    ):
        reasons.append("domain_reasoning")

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
