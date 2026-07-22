"""One-pass Chat response and route selection for PETIT."""
from __future__ import annotations

import json
import re
from typing import Any

from . import config
from .lmstudio_client import LMStudioError, chat_completion, set_prefetched_chat

_SUGGESTIBLE_TOOLS = (
    "get_current_time",
    "get_weather",
    "get_schedule",
    "get_tasks",
    "search_memory",
    "search_brain_notes",
    "search_notion",
    "search_news",
    "create_daily_briefing",
    "restore_context",
    "create_task",
    "update_task",
    "complete_task",
    "get_task_sync_status",
    "retry_task_sync",
    "add_schedule",
    "save_memory",
    "create_handoff_note",
    "edit_brain_note",
    "sync_notion_tasks",
    "sync_calendar",
    "sync_obsidian_vault",
)
_ROUTER_SYSTEM_PROMPT = f"""PETITの経路選択器。JSONだけ返し、Markdownは禁止。
reply=通常会話や一般知識を短く返す。
tool=保存済み・外部情報の取得または変更。
agent=設計、分析、比較、レビュー。
形式:
{{"type":"reply","reply":"返答","confidence":0.0}}
{{"type":"tool","tools":["ツール名"],"reason":"理由","confidence":0.0}}
{{"type":"agent","reason":"理由","confidence":0.0}}
ツール: {', '.join(_SUGGESTIBLE_TOOLS)}
一覧外のツール、引数、実行結果は作らない。"""

_FALLBACK_AGENT_PHRASES = (
    "改善案", "比較して", "設計して", "評価して", "分析して", "計画を立て",
    "レビューして", "検証して", "デバッグして", "実装して", "修正して",
)
_FALLBACK_TOOL_TERMS = (
    "タスク", "予定", "カレンダー", "notion", "brain", "記憶", "覚えて",
    "検索", "ニュース", "天気", "今何時", "今日何日", "同期", "github",
)


def suggestible_tool_names() -> tuple[str, ...]:
    """Return the bounded set that the lightweight router may suggest."""
    return _SUGGESTIBLE_TOOLS


def validate_suggested_tools(values: Any) -> list[str]:
    """Drop hallucinated, duplicate, or privileged tool names from router output."""
    allowed = set(_SUGGESTIBLE_TOOLS)
    names: list[str] = []
    for value in values or []:
        if not isinstance(value, str):
            continue
        name = value.strip()
        if name in allowed and name not in names:
            names.append(name)
        if len(names) >= 5:
            break
    return names


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


def _confidence(data: dict[str, Any]) -> float | None:
    try:
        return max(0.0, min(1.0, float(data.get("confidence"))))
    except (TypeError, ValueError):
        return None


def _fallback(user_message: str) -> dict[str, Any]:
    lowered = user_message.casefold()
    if any(term.casefold() in lowered for term in _FALLBACK_TOOL_TERMS):
        kind = "agent"
        decision_type = "tool"
        reason = "fallback_tool_or_context"
    elif any(phrase.casefold() in lowered for phrase in _FALLBACK_AGENT_PHRASES):
        kind = "agent"
        decision_type = "agent"
        reason = "fallback_reasoning"
    elif user_message.count("\n") >= 4:
        kind = "agent"
        decision_type = "agent"
        reason = "fallback_multi_part"
    else:
        kind = "chat"
        decision_type = "reply"
        reason = "fallback_simple_conversation"
    return {
        "kind": kind,
        "decision_type": decision_type,
        "model": config.AGENT_MODEL if kind == "agent" else config.CHAT_MODEL,
        "reasons": [reason],
        "router_source": "fallback",
        "router_confidence": None,
        "suggested_tools": [],
    }


def choose(
    user_message: str,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Generate a Chat reply or request Agent/tool handling in one model call."""
    text = user_message.strip()
    if not text:
        return _fallback(text)

    messages: list[dict[str, Any]] = [{"role": "system", "content": _ROUTER_SYSTEM_PROMPT}]
    for item in (history or [])[-4:]:
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": f"メッセージ: {text}"})

    try:
        response = chat_completion(
            messages,
            tools=None,
            temperature=0.2,
            model=config.CHAT_MODEL,
            max_tokens=192,
            route="chat",
        )
        parsed = _extract_json(str(response.get("content") or ""))
    except LMStudioError:
        parsed = None

    if not parsed:
        return _fallback(text)

    route_type = str(parsed.get("type") or "").strip().casefold()
    confidence = _confidence(parsed)

    if route_type == "reply":
        reply = str(parsed.get("reply") or "").strip()
        if not reply:
            return _fallback(text)
        set_prefetched_chat(text, reply)
        return {
            "kind": "chat",
            "decision_type": "reply",
            "model": config.CHAT_MODEL,
            "reasons": ["ai_router:reply"],
            "router_source": "ai",
            "router_confidence": confidence,
            "suggested_tools": [],
            "prefetched_reply": True,
        }

    if route_type not in {"tool", "agent"}:
        return _fallback(text)

    reason = str(parsed.get("reason") or route_type).strip()[:120]
    suggested_tools = validate_suggested_tools(parsed.get("tools")) if route_type == "tool" else []
    return {
        "kind": "agent",
        "decision_type": route_type,
        "model": config.AGENT_MODEL,
        "reasons": [f"ai_router:{route_type}", reason],
        "router_source": "ai",
        "router_confidence": confidence,
        "suggested_tools": suggested_tools,
    }


def can_defer(user_message: str, route: dict[str, Any]) -> bool:
    """Deferred chat turns were removed; keep this compatibility helper false."""
    del user_message, route
    return False
