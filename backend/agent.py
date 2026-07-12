"""Minimal conversation flow for PETIT.

The default path is deliberately boring: one chat-model call, a short prompt,
and only the last five conversation turns.  Retrieval and situation gathering
are opt-in through explicit tool routing.
"""
from __future__ import annotations

import json
from typing import Any

from . import config, db, recall, situation, tools  # recall/situation kept import-compatible; never used for chat
from .lmstudio_client import LMStudioError, chat_completion

SYSTEM_PROMPT = (
    "あなたはPETIT。ユーザー専用の相棒です。自然で短い日本語で答えてください。"
    "聞かれていない情報や長い説明は足さず、通常は1〜3文で返してください。"
    "ツール結果がある場合だけ、その事実を使って答えてください。"
)

_NAME_PREFIXES = ("petit", "PETIT", "Petit", "プチ", "ぺち")
_GREETING_REPLIES = {
    "おはよう": "おはよう。今日も短くいこう。",
    "おはよ": "おはよ。今日も短くいこう。",
    "こんにちは": "こんにちは。どうする？",
    "こんにちわ": "こんにちは。どうする？",
    "こんばんは": "こんばんは。おつかれさま、どうする？",
    "こんばんわ": "こんばんは。おつかれさま、どうする？",
    "やっほー": "やっほー。どうした？",
    "やほ": "やほ。どうした？",
    "ただいま": "おかえり。何からやる？",
    "おつかれ": "おつかれさま。少し休もう。",
    "お疲れ": "おつかれさま。少し休もう。",
    "おやすみ": "おやすみ。今日はここまでにしよう。",
}

# Only these tools can enter an ordinary chat request.  Search/summary/RAG
# tools are never selected implicitly.
_TOOL_SIGNALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("get_current_time", ("今何時", "現在時刻", "今の時間", "今日何日", "日付")),
    ("get_tasks", ("タスク", "やること", "todo", "やる事")),
    ("get_schedule", ("予定", "カレンダー", "明日何ある", "今日何ある")),
    ("search_memory", ("過去", "記憶", "覚えてる", "どこまで", "前に", "思い出")),
    ("save_memory", ("覚えておいて", "記憶して", "記録して")),
    ("summarize_now", ("まとめて", "要約して")),
    ("get_weather", ("天気", "気温")),
    ("search_news", ("ニュース", "最新情報")),
    ("start_background_research", ("調べておいて", "調査して")),
    ("create_daily_briefing", ("朝のブリーフィング", "最初の一手")),
    ("restore_context", ("復帰", "続きに戻", "中断から")),
    ("create_handoff_note", ("引き継ぎ", "中断する")),
    ("create_task", ("タスクにして", "タスクを作", "追加して")),
    ("complete_task", ("完了にして", "終わった", "タスクを完了")),
    ("add_schedule", ("予定を入", "予定に追加")),
    ("sync_notion_tasks", ("notionを同期", "Notionを同期")),
    ("sync_calendar", ("カレンダーを同期", "予定を同期")),
    ("sync_obsidian_vault", ("vaultを同期", "再インデックス")),
)


def _compact(text: str) -> str:
    return "".join(ch for ch in text.strip() if ch.isalnum() or ch in ("ー", "疲"))


def _instant_reply(user_message: str) -> dict[str, Any] | None:
    compact = _compact(user_message)
    for name in _NAME_PREFIXES:
        if compact.startswith(name):
            compact = compact[len(name):]
        if compact.endswith(name):
            compact = compact[:-len(name)]
    reply = _GREETING_REPLIES.get(compact)
    if reply is None:
        return None
    return {"reply": reply, "used_tools": [], "model_route": {"kind": "instant", "model": None, "reasons": ["instant_greeting"]}}


def _recent_history(history: list[dict[str, str]] | None) -> list[dict[str, str]]:
    """Keep five user/assistant exchanges (never system or tool context)."""
    clean = [
        {"role": item.get("role", "user"), "content": str(item.get("content", ""))}
        for item in (history or [])
        if item.get("role") in {"user", "assistant"} and item.get("content")
    ]
    return clean[-10:]


def _related_tool_names(message: str) -> list[str]:
    text = message.casefold()
    names: list[str] = []
    for name, signals in _TOOL_SIGNALS:
        if any(signal.casefold() in text for signal in signals):
            names.append(name)
    # A read request should not accidentally expose write tools just because
    # both contain the word "task".
    if "get_tasks" in names and any(x in text for x in ("作って", "追加", "完了", "終わった")):
        names.remove("get_tasks")
    if "get_schedule" in names and "入" in text:
        names.remove("get_schedule")
    return names


def _selected_schemas(names: list[str]) -> list[dict[str, Any]]:
    allowed = set(names)
    return [item for item in tools.openai_tools_schema() if item["function"]["name"] in allowed]


def _format_direct_time(result: str) -> str | None:
    try:
        data = json.loads(result)
    except json.JSONDecodeError:
        return None
    if not data.get("ok"):
        return None
    return f"今は {data['time']} です（{data['date']}・{data['weekday']}、{data['timezone']}）。"


def _tool_result_message(user_message: str, results: list[dict[str, str]]) -> dict[str, str]:
    lines = [f"元の発話: {user_message}", "Python側で実行した結果を使って、短く自然に答えてください。"]
    for item in results:
        lines.append(f"\nツール: {item['name']}\n結果: {item['content']}")
    return {"role": "user", "content": "\n".join(lines)}


def run(user_message: str, history: list[dict[str, str]] | None = None, *, allow_defer: bool = True) -> dict[str, Any]:
    del allow_defer  # Kept for worker/API compatibility; deferred chat is removed.
    instant = _instant_reply(user_message)
    if instant is not None:
        return instant

    tool_names = _related_tool_names(user_message)
    # Current time is deterministic and does not need an LLM at all.
    if tool_names == ["get_current_time"]:
        raw = tools.dispatch("get_current_time", {})
        direct = _format_direct_time(raw)
        if direct:
            return {"reply": direct, "used_tools": [{"name": "get_current_time", "arguments": "{}"}], "model_route": {"kind": "direct", "model": None}}

    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(_recent_history(history))
    messages.append({"role": "user", "content": user_message})
    selected_tools = _selected_schemas(tool_names)
    used_tools: list[dict[str, Any]] = []

    # One call for normal chat. Explicit tool requests may need one additional
    # call to phrase the tool result; they still never receive unrelated tools.
    for _ in range(min(config.MAX_TOOL_ITERATIONS, 2)):
        message = chat_completion(
            messages,
            tools=selected_tools or None,
            model=config.CHAT_MODEL,
        )
        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            return {
                "reply": (message.get("content") or "").strip(),
                "used_tools": used_tools,
                "model_route": {"kind": "chat", "model": config.CHAT_MODEL, "tools": tool_names},
            }
        results: list[dict[str, str]] = []
        for call in tool_calls:
            function = call.get("function", {})
            name = function.get("name", "")
            args = function.get("arguments", "{}")
            result = tools.dispatch(name, args)
            used_tools.append({"name": name, "arguments": args})
            results.append({"name": name, "content": result})
        messages.append(_tool_result_message(user_message, results))
        selected_tools = []

    return {"reply": "確認した結果を短くまとめられませんでした。", "used_tools": used_tools, "model_route": {"kind": "chat", "model": config.CHAT_MODEL, "tools": tool_names}}
