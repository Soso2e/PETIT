"""Minimal conversation flow for PETIT.

The default path is deliberately boring: one chat-model call, a short prompt,
and only the last five conversation turns.  Retrieval and situation gathering
are opt-in through explicit tool routing.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any

from . import config, db, recall, situation, tools  # recall/situation kept import-compatible; never used for chat
from .lmstudio_client import LMStudioError, chat_completion

SYSTEM_PROMPT = (
    "あなたはPETIT。ユーザー専用の相棒です。自然で短い日本語で答えてください。"
    "聞かれていない情報や長い説明は足さず、通常は1〜3文で返してください。"
    "ツール結果がある場合だけ、その事実を使って答えてください。"
    "書き込みを頼まれたら対象確認後に書き込みツールを呼び、実行結果なしに完了したと言わないでください。"
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

# Fast local intent routing keeps casual chat tool-free. Contextual planning
# patterns may expose a bounded read-only set so the agent model can choose the
# necessary source without loading every source first.
_TOOL_SIGNALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("get_current_time", ("今何時", "現在時刻", "今の時間", "今日何日", "日付")),
    ("get_tasks", ("タスク", "やること", "todo", "やる事")),
    ("get_schedule", ("予定", "カレンダー", "明日何ある", "今日何ある")),
    ("search_memory", ("過去", "記憶", "覚えてる", "どこまで", "前に", "思い出")),
    ("search_brain_notes", ("BRAIN", "brain", "vault", "Obsidian", "obsidian")),
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
    ("edit_brain_note", ("BRAINを修正", "BRAINに追記", "brainを修正", "vaultを修正", "ノートを修正", "ノートに追記")),
)

_PLANNING_PATTERN = re.compile(r"(今日|明日|今週).{0,16}(何から|何を|どうする|どうしよう|すれば|優先|始め)")
_RECALL_PATTERN = re.compile(r"(昨日|前回|この前).{0,16}(何|やった|してた|続き|決め)")


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
    """Keep five valid exchanges and discard orphan assistant openers."""
    clean: list[dict[str, str]] = []
    for item in history or []:
        role = item.get("role")
        content = str(item.get("content", "")).strip()
        if role not in {"user", "assistant"} or not content:
            continue
        if not clean and role == "assistant":
            continue
        if clean and clean[-1]["role"] == role:
            clean[-1]["content"] += "\n" + content
        else:
            clean.append({"role": role, "content": content})
    return clean[-10:]


def _related_tool_names(message: str) -> list[str]:
    text = message.casefold()
    names: list[str] = []
    for name, signals in _TOOL_SIGNALS:
        if any(signal.casefold() in text for signal in signals):
            names.append(name)
    # Natural consultations are intents rather than explicit source commands.
    # Expose only the three relevant read tools and let the agent choose among
    # them; no retrieval happens merely because a schema was exposed.
    if _PLANNING_PATTERN.search(message):
        names.extend(("get_tasks", "get_schedule", "search_memory"))
    if _RECALL_PATTERN.search(message):
        names.append("search_memory")
    if any(source in text for source in ("brain", "vault", "obsidian")) and any(
        verb in text for verb in ("追記", "修正", "変更", "書き換", "編集")
    ):
        names.append("edit_brain_note")
    # A read request should not accidentally expose write tools just because
    # both contain the word "task".
    if "get_tasks" in names and any(x in text for x in ("作って", "追加して", "タスクを完了", "完了にして", "終わった")):
        names.remove("get_tasks")
    if "get_schedule" in names and "入" in text:
        names.remove("get_schedule")
    return list(dict.fromkeys(names))


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
    lines = [
        f"元の発話: {user_message}",
        "Python側で実行した結果を使ってください。元の要求が未完了なら残りの適切なツールを呼び、実行結果なしに完了したと言わないでください。",
    ]
    for item in results:
        lines.append(f"\nツール: {item['name']}\n結果: {item['content']}")
    return {"role": "user", "content": "\n".join(lines)}


def _answer(message: dict[str, Any], messages: list[dict[str, Any]], model: str, route: str | None = None) -> str:
    content = (message.get("content") or "").strip()
    if content or message.get("_finish_reason") != "length":
        return content
    retry = chat_completion(messages, tools=None, model=model, route=route or ("agent" if model == config.AGENT_MODEL else "chat"))
    return (retry.get("content") or "").strip()


def _complete(
    messages: list[dict[str, Any]], *, tools_schema: list[dict[str, Any]] | None,
    route: str, allow_chat_fallback: bool = False,
) -> tuple[dict[str, Any], str, str | None]:
    """Call the selected endpoint; only safe read results may be rephrased by chat."""
    try:
        return chat_completion(messages, tools=tools_schema, model=config.AGENT_MODEL if route == "agent" else config.CHAT_MODEL, route=route), route, None
    except LMStudioError:
        if route != "agent" or not allow_chat_fallback:
            raise
        message = chat_completion(messages, tools=None, model=config.CHAT_MODEL, route="chat")
        return message, "chat_fallback", "agent_unavailable"


def _route_meta(requested: str, actual: str, tools_used: list[str], fallback_reason: str | None = None) -> dict[str, Any]:
    endpoint_id = "chat" if actual == "chat_fallback" else actual
    model = config.CHAT_MODEL if endpoint_id == "chat" else config.AGENT_MODEL
    return {
        "kind": requested,
        "requested_route": requested,
        "actual_route": actual,
        "fallback_reason": fallback_reason,
        "model": model,
        "base_url_id": endpoint_id,
        "tools": tools_used,
    }


def _tool_failed(result: str) -> bool:
    if result.startswith("[error]"):
        return True
    try:
        data = json.loads(result)
    except json.JSONDecodeError:
        return False
    if not isinstance(data, dict):
        return False
    return bool(data.get("error")) or any(data.get(key) is False for key in ("ok", "created", "completed", "added", "saved", "updated"))


def _confirmation_text(name: str, args: dict[str, Any]) -> str:
    labels = {
        "create_task": "タスクを作成",
        "add_task": "ローカルタスクを作成",
        "complete_task": "タスクを完了",
        "add_schedule": "PETITのローカル予定へ追加（ICS/Google Calendar本体は変更しません）",
        "save_memory": "長期記憶へ保存",
        "create_handoff_note": "引き継ぎメモを保存",
        "edit_brain_note": "BRAINノートを変更",
    }
    details = "\n".join(f"- {key}: {value}" for key, value in args.items() if value not in (None, ""))
    return f"書き込み前に確認します。\n操作: {labels.get(name, name)}\n{details}\nこの内容で実行しますか？"


def _direct_brain_append(user_message: str) -> dict[str, Any] | None:
    path_match = re.search(r"[「\"]([^」\"]+\.md)[」\"]", user_message, re.IGNORECASE)
    content_match = re.search(r"\.md[」\"].*?に[「\"](.+?)[」\"]と(?:追記|追加)", user_message, re.DOTALL | re.IGNORECASE)
    if not path_match or not content_match:
        return None
    args = {
        "relative_path": path_match.group(1),
        "mode": "append",
        "content": content_match.group(1),
    }
    return {
        "reply": _confirmation_text("edit_brain_note", args),
        "used_tools": [],
        "pending_actions": [{"name": "edit_brain_note", "arguments": args}],
        "persist": True,
        "model_route": {"kind": "direct_write_proposal", "model": None, "tools": ["edit_brain_note"]},
    }


def _run_planning_consultation(user_message: str, history: list[dict[str, str]] | None) -> dict[str, Any]:
    calls = [
        ("get_tasks", {"limit": 10}),
        ("get_schedule", {"date": date.today().isoformat()}),
        ("search_brain_notes", {"query": user_message, "limit": 3}),
    ]
    results: list[dict[str, str]] = []
    used_tools: list[dict[str, Any]] = []
    failed = False
    for name, args in calls:
        content = tools.dispatch(name, args)
        failed = failed or _tool_failed(content)
        results.append({"name": name, "content": content})
        used_tools.append({"name": name, "arguments": json.dumps(args, ensure_ascii=False)})

    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(_recent_history(history))
    messages.append(_tool_result_message(user_message, results))
    answer, actual, fallback_reason = _complete(messages, tools_schema=None, route="agent", allow_chat_fallback=True)
    return {
        "reply": _answer(answer, messages, config.CHAT_MODEL if actual == "chat_fallback" else config.AGENT_MODEL, "chat" if actual == "chat_fallback" else "agent"),
        "used_tools": used_tools,
        "persist": not failed,
        "model_route": _route_meta("agent", actual, [name for name, _ in calls], fallback_reason) | {"kind": "planning"},
    }


def _run_forced_read(
    user_message: str,
    history: list[dict[str, str]] | None,
    name: str,
) -> dict[str, Any]:
    args: dict[str, Any]
    if name == "get_schedule":
        target = date.today() + (timedelta(days=1) if "明日" in user_message else timedelta())
        args = {"date": target.isoformat()}
    elif name == "get_tasks":
        limit_match = re.search(r"(\d+)件", user_message)
        args = {"limit": int(limit_match.group(1))} if limit_match else {"limit": 10}
    else:
        args = {"query": user_message, "limit": 5}
    content = tools.dispatch(name, args)
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(_recent_history(history))
    messages.append(_tool_result_message(user_message, [{"name": name, "content": content}]))
    answer, actual, fallback_reason = _complete(messages, tools_schema=None, route="agent", allow_chat_fallback=True)
    return {
        "reply": _answer(answer, messages, config.CHAT_MODEL if actual == "chat_fallback" else config.AGENT_MODEL, "chat" if actual == "chat_fallback" else "agent"),
        "used_tools": [{"name": name, "arguments": json.dumps(args, ensure_ascii=False)}],
        "persist": not _tool_failed(content),
        "model_route": _route_meta("agent", actual, [name], fallback_reason) | {"kind": "forced_read"},
    }


def run(user_message: str, history: list[dict[str, str]] | None = None, *, allow_defer: bool = True) -> dict[str, Any]:
    del allow_defer  # Kept for worker/API compatibility; deferred chat is removed.
    tool_names = _related_tool_names(user_message)
    write_requested = any(tools.requires_confirmation(name) for name in tool_names)
    if "edit_brain_note" in tool_names:
        direct_brain_edit = _direct_brain_append(user_message)
        if direct_brain_edit:
            return direct_brain_edit
    if _PLANNING_PATTERN.search(user_message):
        return _run_planning_consultation(user_message, history)
    if not write_requested and len(tool_names) == 1 and tool_names[0] in {"get_tasks", "get_schedule", "search_brain_notes"}:
        return _run_forced_read(user_message, history, tool_names[0])
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
    attempted_tool_names: set[str] = set()
    had_tool_failure = False

    # One call for normal chat. Explicit tool requests may need one additional
    # call to phrase the tool result; they still never receive unrelated tools.
    for _ in range(min(config.MAX_TOOL_ITERATIONS, 2)):
        requested_route = "agent" if tool_names else "chat"
        message, actual_route, fallback_reason = _complete(
            messages, tools_schema=selected_tools or None, route=requested_route,
            # Tool selection and writes are not safe to silently degrade.
            allow_chat_fallback=False,
        )
        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            model = config.AGENT_MODEL if tool_names else config.CHAT_MODEL
            if write_requested:
                return {
                    "reply": "対象は確認できましたが、安全な変更案を確定できませんでした。対象ファイルと変更内容をもう少し具体的にしてください。",
                    "used_tools": used_tools,
                    "persist": False,
                    "model_route": _route_meta(requested_route, actual_route, tool_names, fallback_reason),
                }
            return {
                "reply": _answer(message, messages, model, "chat" if actual_route == "chat_fallback" else requested_route),
                "used_tools": used_tools,
                "persist": not had_tool_failure,
                "model_route": _route_meta(requested_route, actual_route, tool_names, fallback_reason),
            }
        results: list[dict[str, str]] = []
        for call in tool_calls:
            function = call.get("function", {})
            name = function.get("name", "")
            args = function.get("arguments", "{}")
            if tools.requires_confirmation(name):
                try:
                    parsed_args = tools.parse_arguments(name, args)
                except ValueError:
                    return {
                        "reply": "書き込み内容を解釈できませんでした。内容を具体的にしてもう一度お願いします。",
                        "used_tools": [],
                        "persist": False,
                        "model_route": _route_meta("agent", "agent", tool_names),
                    }
                return {
                    "reply": _confirmation_text(name, parsed_args),
                    "used_tools": used_tools,
                    "pending_actions": [{"name": name, "arguments": parsed_args}],
                    "persist": True,
                    "model_route": _route_meta("agent", "agent", tool_names),
                }
            result = tools.dispatch(name, args)
            attempted_tool_names.add(name)
            had_tool_failure = had_tool_failure or _tool_failed(result)
            used_tools.append({"name": name, "arguments": args})
            results.append({"name": name, "content": result})
        messages.append(_tool_result_message(user_message, results))
        selected_tools = _selected_schemas([name for name in tool_names if name not in attempted_tool_names])

    requested_route = "agent" if tool_names else "chat"
    return {"reply": "確認した結果を短くまとめられませんでした。", "used_tools": used_tools, "persist": False, "model_route": _route_meta(requested_route, requested_route, tool_names)}
