"""AI-assisted routing between PETIT's chat and agent models."""
from __future__ import annotations

import json
import re
from typing import Any

from . import config
from .lmstudio_client import LMStudioError, chat_completion

_ROUTER_SYSTEM_PROMPT = """あなたはPETITの軽量ルーターです。
ユーザーのメッセージを処理する経路だけ判定してください。

- chat: 普通の会話、短い質問、感想、相づち。外部情報や深い分析が不要
- agent: 分析、比較、設計、評価、計画、コードレビューなど、強い推論が必要
- tool: 現在時刻、天気、予定、タスク、記憶、BRAIN、ニュースなど、PETIT外または保存済み情報の取得・変更が必要

必ず次のJSONだけを返してください。説明やMarkdownは禁止です。
{"route":"chat|agent|tool","confidence":0.0,"reason":"短い理由"}
書き込みの実行可否やツール引数は判定しないでください。"""

# The fallback is intentionally conservative. It is used only when the routing
# model is unavailable or returns malformed output; normal routing is semantic.
_FALLBACK_AGENT_PHRASES = (
    "改善案", "比較して", "設計して", "評価して", "分析して", "計画を立て",
    "レビューして", "検証して", "デバッグして", "実装して", "修正して",
)
_FALLBACK_TOOL_TERMS = (
    "タスク", "予定", "カレンダー", "notion", "brain", "記憶", "覚えて",
    "検索", "ニュース", "天気", "今何時", "今日何日", "同期", "github",
)


def _extract_json(content: str) -> dict[str, Any] | None:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _fallback(user_message: str) -> dict[str, Any]:
    lowered = user_message.casefold()
    if any(term.casefold() in lowered for term in _FALLBACK_TOOL_TERMS):
        kind = "agent"
        reason = "fallback_tool_or_context"
    elif any(phrase.casefold() in lowered for phrase in _FALLBACK_AGENT_PHRASES):
        kind = "agent"
        reason = "fallback_reasoning"
    elif user_message.count("\n") >= 4:
        kind = "agent"
        reason = "fallback_multi_part"
    else:
        kind = "chat"
        reason = "fallback_simple_conversation"
    return {
        "kind": kind,
        "model": config.AGENT_MODEL if kind == "agent" else config.CHAT_MODEL,
        "reasons": [reason],
        "router_source": "fallback",
        "router_confidence": None,
    }


def choose(
    user_message: str,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Classify a turn semantically, with a deterministic failure fallback.

    Tool selection and every write approval remain separate in ``agent.py``. The
    router only decides whether ordinary Chat is enough or the Agent path is needed.
    """
    del history  # Keep the classifier small and independent from conversation size.
    text = user_message.strip()
    if not text:
        return _fallback(text)

    messages = [
        {"role": "system", "content": _ROUTER_SYSTEM_PROMPT},
        {"role": "user", "content": f"メッセージ: {text}"},
    ]
    try:
        response = chat_completion(
            messages,
            tools=None,
            temperature=0,
            model=config.CHAT_MODEL,
            max_tokens=96,
            route="chat",
        )
        parsed = _extract_json(str(response.get("content") or ""))
    except LMStudioError:
        parsed = None

    if not parsed:
        return _fallback(text)

    route = str(parsed.get("route") or "").strip().casefold()
    if route not in {"chat", "agent", "tool"}:
        return _fallback(text)

    kind = "agent" if route in {"agent", "tool"} else "chat"
    try:
        confidence = max(0.0, min(1.0, float(parsed.get("confidence"))))
    except (TypeError, ValueError):
        confidence = None
    reason = str(parsed.get("reason") or route).strip()[:120]
    return {
        "kind": kind,
        "model": config.AGENT_MODEL if kind == "agent" else config.CHAT_MODEL,
        "reasons": [f"ai_router:{route}", reason],
        "router_source": "ai",
        "router_confidence": confidence,
    }


def can_defer(user_message: str, route: dict[str, Any]) -> bool:
    """Deferred chat turns were removed; keep this compatibility helper false."""
    del user_message, route
    return False
