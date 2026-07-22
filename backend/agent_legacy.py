"""Minimal conversation flow for PETIT.

The default path keeps ordinary chat to one lightweight model call. Deterministic
commands and explicit tool requests are handled before the AI router; ambiguous
natural-language requests can still use the router's bounded tool suggestions.
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from . import config, db, model_router, project_router, recall, situation, tools  # recall/situation kept import-compatible; never used for chat
from .date_parser import has_schedule_date_expression, parse_schedule_date
from .lmstudio_client import LMStudioError, chat_completion

CHAT_SYSTEM_PROMPT = (
    "あなたはPETIT。ユーザーの相棒として、自然で短い日本語を1〜2文で返してください。"
    "質問に直接答え、思考過程や不要な前置きは出さないでください。"
)
AGENT_SYSTEM_PROMPT = (
    "あなたはPETIT。ユーザーの生活・制作・開発を支える実務的な相棒です。"
    "まず結論を示し、その後に必要な理由・手順・注意点を、要求に十分な長さで説明してください。"
    "設計、分析、比較、レビューでは、短さより正確さと実用性を優先し、必要なら箇条書きを使ってください。"
    "内部の思考過程は出さず、確認できた事実と判断を分けてください。"
    "ツール結果がある場合だけ、その事実を使ってください。"
    "書き込みは対象確認後にツールで実行し、実行結果なしに完了したと言わないでください。"
    "最後に、役立つ場合だけ次の具体的な一手を示してください。"
)
# Compatibility alias for modules/tests that still import the old name.
SYSTEM_PROMPT = AGENT_SYSTEM_PROMPT

_HISTORY_MAX_MESSAGES = 6
_HISTORY_MAX_CHARS = 2400

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
    ("sync_github_evidence", ("githubを同期", "githubの進捗を同期", "github更新を取得", "github evidence")),
    ("get_github_repository_candidates", ("github候補", "githubリポジトリ候補")),
    ("link_github_repository_candidate", ("github候補を紐付け", "githubリポジトリ候補を紐付け")),
    ("ignore_github_repository_candidate", ("github候補を無視", "githubリポジトリ候補を無視")),
    ("sync_calendar", ("カレンダーを同期", "予定を同期")),
    ("sync_obsidian_vault", ("vaultを同期", "再インデックス")),
    ("edit_brain_note", ("BRAINを修正", "BRAINに追記", "brainを修正", "vaultを修正", "ノートを修正", "ノートに追記")),
)

_PLANNING_PATTERN = re.compile(r"(今日|明日|今週).{0,16}(何から|何を|どうする|どうしよう|すれば|優先|始め)")
_RECALL_PATTERN = re.compile(r"(昨日|前回|この前).{0,16}(何|やった|してた|続き|決め)")
_GITHUB_REPOSITORY_PATTERN = re.compile(
    r"(?:[A-Za-z][A-Za-z0-9_.-]*/[A-Za-z0-9_.-]+|[A-Za-z0-9_.-]+/[A-Za-z][A-Za-z0-9_.-]*)"
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
    return {
        "reply": reply,
        "used_tools": [],
        "model_route": {
            "kind": "instant",
            "requested_route": "deterministic",
            "actual_route": "deterministic",
            "model": None,
            "reasons": ["instant_greeting"],
            "tools": [],
        },
    }


def _recent_history(history: list[dict[str, str]] | None) -> list[dict[str, str]]:
    """Keep at most three valid exchanges within a small character budget."""
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

    bounded_reversed: list[dict[str, str]] = []
    remaining = _HISTORY_MAX_CHARS
    for item in reversed(clean[-_HISTORY_MAX_MESSAGES:]):
        if remaining <= 0:
            break
        content = item["content"]
        if len(content) > remaining:
            content = ("…" + content[-(remaining - 1):]) if remaining > 1 else "…"
        bounded_reversed.append({"role": item["role"], "content": content})
        remaining -= len(content)

    bounded = list(reversed(bounded_reversed))
    while bounded and bounded[0]["role"] == "assistant":
        bounded.pop(0)
    return bounded


def _related_tool_names(message: str) -> list[str]:
    text = message.casefold()
    names: list[str] = []
    for name, signals in _TOOL_SIGNALS:
        if any(signal.casefold() in text for signal in signals):
            names.append(name)
    repository_reference = "github.com/" in text or (
        any(marker in text for marker in ("github", "リポジトリ", "repository"))
        and bool(_GITHUB_REPOSITORY_PATTERN.search(message))
    )
    if repository_reference and any(
        verb in text for verb in ("登録", "紐付け", "ひも付け", "確認", "候補")
    ):
        names.append("inspect_github_repository")
    if "link_github_repository_candidate" in names or "ignore_github_repository_candidate" in names:
        names = [name for name in names if name != "get_github_repository_candidates"]
    # Natural consultations are intents rather than explicit source commands.
    # Expose only the relevant read tools and let the agent choose among them.
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


def _validated_router_tool_names(route_decision: dict[str, Any]) -> list[str]:
    if route_decision.get("decision_type") != "tool":
        return []
    registered = set(tools.registered_names())
    return [
        name
        for name in model_router.validate_suggested_tools(route_decision.get("suggested_tools"))
        if name in registered
    ]


def _selected_schemas(names: list[str]) -> list[dict[str, Any]]:
    allowed = set(names)
    return [item for item in tools.openai_tools_schema() if item["function"]["name"] in allowed]


def _deterministic_route(tool_names: list[str], reason: str) -> dict[str, Any]:
    return {
        "kind": "agent",
        "decision_type": "tool",
        "model": config.AGENT_MODEL,
        "reasons": [reason],
        "router_source": "deterministic",
        "router_confidence": 1.0,
        "suggested_tools": [],
        "selected_tools": list(tool_names),
    }


def _route_details(route_decision: dict[str, Any], selected_tools: list[str], tool_result_mode: str) -> dict[str, Any]:
    return {
        "reasons": list(route_decision.get("reasons") or []),
        "router_source": route_decision.get("router_source"),
        "router_confidence": route_decision.get("router_confidence"),
        "router_decision": route_decision.get("decision_type"),
        "suggested_tools": list(route_decision.get("suggested_tools") or []),
        "selected_tools": list(selected_tools),
        "tool_result_mode": tool_result_mode,
    }


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


def _normalize_tool_calls(message: dict[str, Any], tool_round: int) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, raw_call in enumerate(message.get("tool_calls") or []):
        if not isinstance(raw_call, dict):
            continue
        function = raw_call.get("function") or {}
        if not isinstance(function, dict):
            continue
        name = str(function.get("name") or "").strip()
        arguments = function.get("arguments", "{}")
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments or {}, ensure_ascii=False)
        call_id = str(raw_call.get("id") or f"petit_tool_{tool_round}_{index}")
        normalized.append(
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            }
        )
    return normalized


def _append_standard_tool_results(
    messages: list[dict[str, Any]],
    assistant_message: dict[str, Any],
    tool_calls: list[dict[str, Any]],
    results: list[dict[str, str]],
) -> None:
    messages.append(
        {
            "role": "assistant",
            "content": assistant_message.get("content") or None,
            "tool_calls": tool_calls,
        }
    )
    for item in results:
        messages.append(
            {
                "role": "tool",
                "tool_call_id": item["call_id"],
                "name": item["name"],
                "content": item["content"],
            }
        )


def _tool_template_compatibility_error(exc: LMStudioError) -> bool:
    text = str(exc).casefold()
    return any(
        marker in text
        for marker in (
            "error rendering prompt",
            "jinja",
            "no user query found",
            "role=tool",
            "role 'tool'",
            "tool message",
        )
    )


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
        "link_github_repository_candidate": "GitHub repository候補を内部プロジェクトへ紐付け",
        "ignore_github_repository_candidate": "GitHub repository候補を無視対象に変更",
    }
    details = "\n".join(f"- {key}: {value}" for key, value in args.items() if value not in (None, ""))
    return f"書き込み前に確認します。\n操作: {labels.get(name, name)}\n{details}\nこの内容で実行しますか？"


def _fallback_read_reply(name: str, content: str) -> str:
    """Keep safe schedule reads usable when both local model routes are unavailable."""
    if name != "get_schedule":
        return ""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return ""
    if not isinstance(data, dict) or data.get("error"):
        return ""
    events = data.get("events") or []
    sync = data.get("calendar_sync") or {}
    target = str(data.get("date") or "指定日")
    lines = [f"{target}の予定はありません。" if not events else f"{target}の予定は{len(events)}件あります。"]
    for event in events:
        title = str(event.get("title") or "タイトルなし")
        start = str(event.get("start_time") or "時刻未設定")
        lines.append(f"- {title}（{start}）")
    if sync.get("stale"):
        lines.append(f"※ 外部同期に失敗したため、{sync.get('last_synced_at') or '前回同期時'}の古いキャッシュです。")
    return "\n".join(lines)


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

    messages: list[dict[str, Any]] = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}]
    messages.extend(history or [])
    messages.append(_tool_result_message(user_message, results))
    answer, actual, fallback_reason = _complete(messages, tools_schema=None, route="agent", allow_chat_fallback=True)
    return {
        "reply": _answer(answer, messages, config.CHAT_MODEL if actual == "chat_fallback" else config.AGENT_MODEL, "chat" if actual == "chat_fallback" else "agent"),
        "used_tools": used_tools,
        "persist": not failed,
        "model_route": _route_meta("agent", actual, [name for name, _ in calls], fallback_reason) | {"kind": "planning", "tool_result_mode": "user_context"},
    }


def _run_forced_read(
    user_message: str,
    history: list[dict[str, str]] | None,
    name: str,
) -> dict[str, Any]:
    args: dict[str, Any]
    if name == "get_schedule":
        target = parse_schedule_date(user_message)
        if target is None and has_schedule_date_expression(user_message):
            return {
                "reply": "日付を特定できませんでした。2026-07-13、2026年7月13日、7月13日のように指定してください。",
                "used_tools": [],
                "persist": False,
                "model_route": {
                    "kind": "clarification",
                    "requested_route": "deterministic",
                    "actual_route": "deterministic",
                    "fallback_reason": "invalid_or_ambiguous_schedule_date",
                    "model": None,
                    "base_url_id": None,
                    "tools": [],
                },
            }
        args = {"date": (target or date.today()).isoformat()}
    elif name == "get_tasks":
        limit_match = re.search(r"(\d+)件", user_message)
        args = {"limit": int(limit_match.group(1))} if limit_match else {"limit": 10}
    else:
        args = {"query": user_message, "limit": 5}
    content = tools.dispatch(name, args)
    messages: list[dict[str, Any]] = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}]
    messages.extend(history or [])
    messages.append(_tool_result_message(user_message, [{"name": name, "content": content}]))
    try:
        answer, actual, fallback_reason = _complete(messages, tools_schema=None, route="agent", allow_chat_fallback=True)
        reply = _answer(answer, messages, config.CHAT_MODEL if actual == "chat_fallback" else config.AGENT_MODEL, "chat" if actual == "chat_fallback" else "agent")
        model_route = _route_meta("agent", actual, [name], fallback_reason) | {"kind": "forced_read", "tool_result_mode": "user_context"}
    except LMStudioError:
        reply = _fallback_read_reply(name, content)
        if not reply:
            raise
        model_route = {
            "kind": "forced_read",
            "requested_route": "agent",
            "actual_route": "deterministic",
            "fallback_reason": "models_unavailable",
            "model": None,
            "base_url_id": None,
            "tools": [name],
            "tool_result_mode": "deterministic_fallback",
        }
    return {
        "reply": reply or _fallback_read_reply(name, content),
        "used_tools": [{"name": name, "arguments": json.dumps(args, ensure_ascii=False)}],
        "persist": not _tool_failed(content),
        "model_route": model_route,
    }


def run(user_message: str, history: list[dict[str, str]] | None = None, *, allow_defer: bool = True) -> dict[str, Any]:
    del allow_defer  # Kept for worker/API compatibility; deferred chat is removed.
    recent_history = _recent_history(history)
    project_turn = project_router.try_handle_project_turn(
        user_message,
        user_id=config.PETIT_OWNER_ID,
        recent_history=recent_history,
    )
    if project_turn:
        return project_turn

    instant = _instant_reply(user_message)
    if instant:
        return instant

    # Explicit and deterministic tool signals are resolved before paying for the
    # lightweight AI router. The AI router is reserved for ambiguous language.
    tool_names = _related_tool_names(user_message)
    write_requested = any(tools.requires_confirmation(name) for name in tool_names)
    if "edit_brain_note" in tool_names:
        direct_brain_edit = _direct_brain_append(user_message)
        if direct_brain_edit:
            return direct_brain_edit
    if _PLANNING_PATTERN.search(user_message):
        return _run_planning_consultation(user_message, recent_history)
    if not write_requested and len(tool_names) == 1 and tool_names[0] in {"get_tasks", "get_schedule", "search_brain_notes"}:
        return _run_forced_read(user_message, recent_history, tool_names[0])
    if tool_names == ["get_current_time"]:
        raw = tools.dispatch("get_current_time", {})
        direct = _format_direct_time(raw)
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
                    "tool_result_mode": "direct",
                },
            }

    if tool_names:
        route_decision = _deterministic_route(tool_names, "deterministic_tool_signal")
    else:
        route_decision = model_router.choose(user_message, recent_history)
        tool_names = _validated_router_tool_names(route_decision)
        write_requested = any(tools.requires_confirmation(name) for name in tool_names)

    selected_tools = _selected_schemas(tool_names)
    selected_tool_names = {item["function"]["name"] for item in selected_tools}
    used_tools: list[dict[str, Any]] = []
    attempted_calls: set[tuple[str, str]] = set()
    had_tool_failure = False
    requested_route = "agent" if tool_names or route_decision["kind"] == "agent" else "chat"
    prompt = AGENT_SYSTEM_PROMPT if requested_route == "agent" else CHAT_SYSTEM_PROMPT
    base_messages: list[dict[str, Any]] = [{"role": "system", "content": prompt}]
    base_messages.extend(recent_history)
    base_messages.append({"role": "user", "content": user_message})
    standard_messages = list(base_messages)
    compatibility_messages = list(base_messages)
    active_transport = "user" if config.TOOL_RESULT_MODE == "user" else "tool"
    tool_result_mode = "none"
    tool_rounds = 0

    while True:
        call_messages = compatibility_messages if active_transport == "user" else standard_messages
        try:
            message, actual_route, fallback_reason = _complete(
                call_messages,
                tools_schema=selected_tools or None,
                route=requested_route,
                # Pure reasoning can safely degrade to Chat. Tool selection and writes cannot.
                allow_chat_fallback=requested_route == "agent" and not tool_names,
            )
        except LMStudioError as exc:
            can_fallback_transport = (
                config.TOOL_RESULT_MODE == "auto"
                and active_transport == "tool"
                and standard_messages != compatibility_messages
                and _tool_template_compatibility_error(exc)
            )
            if not can_fallback_transport:
                raise
            active_transport = "user"
            tool_result_mode = "user_fallback"
            call_messages = compatibility_messages
            message, actual_route, fallback_reason = _complete(
                call_messages,
                tools_schema=selected_tools or None,
                route=requested_route,
                allow_chat_fallback=False,
            )

        tool_calls = _normalize_tool_calls(message, tool_rounds + 1)
        if not tool_calls:
            model = (
                config.CHAT_MODEL
                if actual_route == "chat_fallback"
                else (config.AGENT_MODEL if requested_route == "agent" else config.CHAT_MODEL)
            )
            route_meta = _route_meta(requested_route, actual_route, tool_names, fallback_reason)
            route_meta.update(_route_details(route_decision, tool_names, tool_result_mode))
            if write_requested:
                return {
                    "reply": "対象は確認できましたが、安全な変更案を確定できませんでした。対象と変更内容をもう少し具体的にしてください。",
                    "used_tools": used_tools,
                    "persist": False,
                    "model_route": route_meta,
                }
            return {
                "reply": _answer(message, call_messages, model, "chat" if actual_route == "chat_fallback" else requested_route),
                "used_tools": used_tools,
                "persist": not had_tool_failure,
                "model_route": route_meta,
            }

        if tool_rounds >= config.MAX_TOOL_ITERATIONS:
            route_meta = _route_meta(requested_route, actual_route, tool_names, "tool_iteration_limit")
            route_meta.update(_route_details(route_decision, tool_names, tool_result_mode))
            return {
                "reply": "必要な確認が多段になったため、ここで停止しました。対象を絞ってもう一度頼んでください。",
                "used_tools": used_tools,
                "persist": False,
                "model_route": route_meta,
            }
        tool_rounds += 1

        results: list[dict[str, str]] = []
        for call in tool_calls:
            function = call["function"]
            name = function["name"]
            args = function["arguments"]
            call_id = call["id"]

            if name not in selected_tool_names:
                result = json.dumps(
                    {"error": "tool_not_allowed", "tool": name},
                    ensure_ascii=False,
                )
                had_tool_failure = True
                results.append({"name": name or "unknown", "content": result, "call_id": call_id})
                continue

            try:
                parsed_args = tools.parse_arguments(name, args)
            except ValueError:
                result = json.dumps(
                    {"error": "invalid_tool_arguments", "tool": name},
                    ensure_ascii=False,
                )
                had_tool_failure = True
                results.append({"name": name, "content": result, "call_id": call_id})
                continue

            signature = (name, json.dumps(parsed_args, ensure_ascii=False, sort_keys=True, default=str))
            if signature in attempted_calls:
                result = json.dumps(
                    {"error": "duplicate_tool_call", "tool": name, "message": "同じ引数の再実行を停止しました。"},
                    ensure_ascii=False,
                )
                had_tool_failure = True
                results.append({"name": name, "content": result, "call_id": call_id})
                continue
            attempted_calls.add(signature)

            if tools.requires_confirmation(name):
                route_meta = _route_meta("agent", "agent", tool_names)
                route_meta.update(_route_details(route_decision, tool_names, tool_result_mode))
                return {
                    "reply": _confirmation_text(name, parsed_args),
                    "used_tools": used_tools,
                    "pending_actions": [{"name": name, "arguments": parsed_args}],
                    "persist": True,
                    "model_route": route_meta,
                }

            result = tools.dispatch(name, parsed_args)
            had_tool_failure = had_tool_failure or _tool_failed(result)
            used_tools.append({"name": name, "arguments": json.dumps(parsed_args, ensure_ascii=False)})
            results.append({"name": name, "content": result, "call_id": call_id})

        _append_standard_tool_results(standard_messages, message, tool_calls, results)
        compatibility_messages.append(_tool_result_message(user_message, results))
        if tool_result_mode == "none":
            tool_result_mode = "user" if active_transport == "user" else "tool"
