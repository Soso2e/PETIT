"""One-pass PETIT Brain entry and bounded route selection."""
from __future__ import annotations

import json
import re
from typing import Any

from . import config, context_broker, situation, time_context, tools
from .lmstudio_client import LMStudioError, chat_completion
from .petit_prompt import CORE_SYSTEM_PROMPT

CAPABILITY_GROUPS: dict[str, tuple[str, ...]] = {
    "lists_and_tasks": (
        "get_lists", "get_list_items", "create_list", "add_list_item", "get_tasks",
        "create_task", "update_task", "set_task_parent", "complete_task",
        "get_task_sync_status", "retry_task_sync", "sync_notion_tasks",
    ),
    "work_sessions": (
        "get_work_status", "get_work_report", "start_work_session", "update_work_session", "get_tasks",
    ),
    "calendar": (
        "get_current_time", "get_schedule", "add_schedule", "sync_calendar",
        "create_reminder", "get_reminders", "manage_reminder", "get_weather",
    ),
    "knowledge": (
        "search_memory", "search_brain_notes", "search_notion", "edit_brain_note", "sync_obsidian_vault",
    ),
    "github": (
        "review_github_activity", "sync_github_evidence", "get_github_repository_candidates",
        "link_github_repository_candidate", "ignore_github_repository_candidate", "inspect_github_repository",
    ),
    "web": ("search_news", "start_background_research"),
    "memory": (
        "save_memory", "summarize_now", "create_daily_briefing", "restore_context", "create_handoff_note",
    ),
    "projects": (
        "get_project_status", "get_tasks", "get_notion_project_candidates",
        "get_linkraft_project_candidates", "get_brain_note_candidates", "get_github_repository_candidates",
        "sync_notion_tasks", "sync_linkraft_projects", "sync_github_evidence",
    ),
    "fallback_read": (
        "get_lists", "get_list_items", "get_tasks", "get_task_sync_status", "get_current_time",
        "get_schedule", "get_reminders", "get_weather", "search_memory", "search_brain_notes",
        "search_notion", "review_github_activity", "inspect_github_repository", "search_news",
        "get_project_status", "get_notion_project_candidates", "get_linkraft_project_candidates",
        "get_brain_note_candidates", "get_github_repository_candidates", "get_work_status", "get_work_report",
    ),
}

_GROUP_DESCRIPTIONS = {
    "lists_and_tasks": "タスク、Notionタスク、親子関係、任意リストの取得・追加・変更",
    "work_sessions": "作業中の状態、作業時間の開始・停止・再開、今日や期間別の作業記録",
    "calendar": "時刻、天気、予定、リマインダー、カレンダーの取得・追加・変更・同期",
    "knowledge": "BRAIN、Notion、記憶の検索と確認付き編集",
    "github": "GitHubのリポジトリ、差分、PR、開発状況",
    "web": "ニュースや外部調査",
    "memory": "長期記憶、要約、復帰、引き継ぎ、ブリーフィング",
    "projects": "PETIT内部プロジェクトと外部ソースの継続管理",
}

_ROUTABLE_GROUPS = tuple(_GROUP_DESCRIPTIONS)
_ONE_PASS_MAX_TOKENS = max(config.LIGHT_MAX_TOKENS, 1024)
_ROUTER_SYSTEM_PROMPT = CORE_SYSTEM_PROMPT + """

この会話入口では次の3択で行動してください。
1. 手元の会話だけで答えられるなら、その場で最終回答する。
2. タスクまたは予定の読み取り情報だけ足りないなら request_context をcallする。
3. 書き込み、複雑な調査、BRAIN/Memory/GitHub等、Context Broker対象外の処理が必要なら route_to_agent をcallする。

request_contextではTool名を選ばず、必要な情報の種類だけを指定してください。現在対応するsourceは tasks と calendar だけです。
"""

_REQUEST_CONTEXT_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "request_context",
        "description": "PETITが自然に回答するために不足している読み取り専用Contextを取得する。現在はtasks/calendarのみ。",
        "parameters": {
            "type": "object",
            "properties": {
                "needs": {
                    "type": "array",
                    "maxItems": 4,
                    "items": {
                        "type": "object",
                        "properties": {
                            "source": {"type": "string", "enum": ["tasks", "calendar"]},
                            "scope": {"type": "string", "description": "today/tomorrow等の必要範囲"},
                            "priority": {"type": "string", "enum": ["High", "Mid", "Low", "all"]},
                            "date": {"type": "string", "description": "必要ならYYYY-MM-DD"},
                        },
                        "required": ["source"],
                        "additionalProperties": False,
                    },
                },
                "goal": {"type": "string", "description": "取得したContextで答えたいこと"},
            },
            "required": ["needs", "goal"],
            "additionalProperties": False,
        },
    },
}

_ROUTE_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "route_to_agent",
        "description": "Context Brokerだけでは完了できない操作・複雑処理をAgent Runtimeへ引き渡す。",
        "parameters": {
            "type": "object",
            "properties": {
                "capabilities": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(_ROUTABLE_GROUPS)},
                    "maxItems": 4,
                },
                "goal": {"type": "string"},
                "confidence": {"type": "number"},
            },
            "required": ["capabilities", "goal"],
            "additionalProperties": False,
        },
    },
}

_ACTION_WORDS = r"(?:教えて|見せて|確認|調べ|検索|取得|一覧|追加|作成|登録|変更|更新|編集|完了|削除|同期|実行|開始|停止|保存|直して|レビュー)"
_WRITE_WORDS = re.compile(r"(?:追加|作成|登録|変更|更新|編集|完了|削除|同期|実行|開始|停止|保存|直して)")
_TOOL_GUARD_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("work_sessions", re.compile(r"(?:作業|集中|タイマー|計測).{0,24}(?:開始|始め|ストップ|停止|終了|中断|休憩|一時停止|再開|続け|何分|何時間|履歴|記録|集計|状況|作業中)|(?:今日|今週|最近).{0,16}(?:何分|何時間).{0,12}(?:作業|集中)|(?:何分|何時間).{0,16}(?:作業|集中)")),
    ("lists_and_tasks", re.compile(rf"(?:タスク|todo|TODO|リスト|Notionタスク).{{0,24}}{_ACTION_WORDS}|{_ACTION_WORDS}.{{0,24}}(?:タスク|todo|TODO|リスト|Notionタスク)")),
    ("calendar", re.compile(rf"(?:予定|スケジュール|カレンダー|リマインダー|天気|現在時刻|今何時).{{0,24}}{_ACTION_WORDS}|{_ACTION_WORDS}.{{0,24}}(?:予定|スケジュール|カレンダー|リマインダー|天気|現在時刻|今何時)")),
    ("knowledge", re.compile(rf"(?:BRAIN|Obsidian|Notion|ノーション|記憶|メモ).{{0,24}}{_ACTION_WORDS}|{_ACTION_WORDS}.{{0,24}}(?:BRAIN|Obsidian|Notion|ノーション|記憶|メモ)")),
    ("github", re.compile(rf"(?:GitHub|リポジトリ|コミット|PR|プルリク|差分|CI).{{0,24}}{_ACTION_WORDS}|{_ACTION_WORDS}.{{0,24}}(?:GitHub|リポジトリ|コミット|PR|プルリク|差分|CI)")),
    ("web", re.compile(r"(?:最新|現在|今日).{0,16}(?:ニュース|情報|状況|価格|仕様)|(?:ニュース|外部情報|ウェブ|Web).{0,24}(?:検索|調べ|確認)")),
    ("projects", re.compile(rf"(?:プロジェクト|PJ|開発状況).{{0,24}}{_ACTION_WORDS}|{_ACTION_WORDS}.{{0,24}}(?:プロジェクト|PJ|開発状況)")),
)


def _extract_json(content: str) -> dict[str, Any] | None:
    text = str(content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _confidence(value: Any) -> float | None:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def validate_capabilities(values: Any) -> list[str]:
    result: list[str] = []
    for value in values or []:
        name = str(value or "").strip()
        if name in _ROUTABLE_GROUPS and name not in result:
            result.append(name)
        if len(result) >= 4:
            break
    return result


def tool_names_for(capabilities: list[str]) -> list[str]:
    registered = set(tools.registered_names())
    result: list[str] = []
    for capability in capabilities:
        for name in CAPABILITY_GROUPS.get(capability, ()):
            if name in registered and name not in result:
                result.append(name)
    return result


def _fallback(text: str, context: str) -> dict[str, Any]:
    goal = text if not context else f"{text}\n\n{context}"
    return {"type": "agent", "capabilities": ["fallback_read"], "goal": goal, "confidence": None, "source": "safe_fallback"}


def _tool_arguments(message: dict[str, Any], name: str) -> dict[str, Any] | None:
    for raw in message.get("tool_calls") or []:
        if not isinstance(raw, dict):
            continue
        function = raw.get("function") or {}
        if not isinstance(function, dict) or function.get("name") != name:
            continue
        arguments = function.get("arguments") or "{}"
        try:
            parsed = json.loads(arguments) if isinstance(arguments, str) else dict(arguments)
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _route_arguments(message: dict[str, Any]) -> dict[str, Any] | None:
    return _tool_arguments(message, "route_to_agent")


def _required_capabilities(text: str, history: list[dict[str, str]] | None = None) -> list[str]:
    combined_parts = [str(text or "")]
    for item in (history or [])[-2:]:
        if item.get("role") == "user":
            combined_parts.append(str(item.get("content") or ""))
    combined = "\n".join(combined_parts)
    result: list[str] = []
    for capability, pattern in _TOOL_GUARD_PATTERNS:
        if pattern.search(combined) and capability not in result:
            result.append(capability)
        if len(result) >= 4:
            break
    return result


def _read_context_fallback(text: str, required: list[str]) -> dict[str, Any] | None:
    if _WRITE_WORDS.search(text):
        return None
    supported = set(required)
    if supported and supported.issubset({"lists_and_tasks", "calendar"}):
        needs: list[dict[str, str]] = []
        if "lists_and_tasks" in supported:
            needs.append({"source": "tasks", "priority": "High"})
        if "calendar" in supported:
            scope = "tomorrow" if "明日" in text else "today" if "今日" in text else ""
            need = {"source": "calendar"}
            if scope:
                need["scope"] = scope
            needs.append(need)
        return {
            "type": "context",
            "context_request": {"needs": needs, "goal": text},
            "confidence": None,
            "source": "forced_context_guard",
        }
    return None


def _continue_truncated_reply(messages: list[dict[str, Any]], first: dict[str, Any]) -> str:
    content = str(first.get("content") or "").strip()
    if first.get("_finish_reason") != "length" or not content:
        return content
    continuation_messages = list(messages)
    continuation_messages.append({"role": "assistant", "content": content})
    continuation_messages.append({"role": "user", "content": "直前の回答が出力上限で途中終了しました。内容を繰り返さず、途切れた箇所から続きを完結させてください。"})
    try:
        continuation = chat_completion(
            continuation_messages, tools=None, temperature=0.2,
            model=config.CHAT_MODEL, max_tokens=_ONE_PASS_MAX_TOKENS, route="chat",
        )
    except LMStudioError:
        return content
    suffix = str(continuation.get("content") or "").strip()
    return f"{content}\n{suffix}".strip() if suffix else content


def choose(user_message: str, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """Answer once, request bounded read Context, or route to the Deep Agent."""
    text = str(user_message or "").strip()
    recent = history or []
    runtime_context = time_context.prompt_context_for(text, history=recent)
    active_work_context = situation.build_active_work_context()
    situational_context = "\n\n".join(block for block in (runtime_context, active_work_context) if block)

    messages: list[dict[str, Any]] = [{"role": "system", "content": _ROUTER_SYSTEM_PROMPT}]
    for item in recent[-6:]:
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content[:1200]})
    user_content = text if not situational_context else f"{text}\n\n{situational_context}"
    messages.append({"role": "user", "content": user_content})

    try:
        response = chat_completion(
            messages,
            tools=[_REQUEST_CONTEXT_SCHEMA, _ROUTE_TOOL_SCHEMA],
            temperature=0.2,
            model=config.CHAT_MODEL,
            max_tokens=_ONE_PASS_MAX_TOKENS,
            route="chat",
        )
    except LMStudioError:
        return _fallback(text, situational_context)

    context_args = _tool_arguments(response, "request_context")
    if context_args is not None:
        request = context_broker.normalize_request(context_args)
        if request.get("needs"):
            return {
                "type": "context",
                "context_request": request,
                "confidence": None,
                "source": "one_pass_context_request",
            }

    routed = _route_arguments(response)
    if routed is not None:
        capabilities = validate_capabilities(routed.get("capabilities"))
        if not capabilities:
            return _fallback(text, situational_context)
        goal = str(routed.get("goal") or text).strip()[:500]
        if situational_context:
            goal = f"{goal}\n\n{situational_context}"
        return {
            "type": "agent", "capabilities": capabilities, "goal": goal,
            "confidence": _confidence(routed.get("confidence")), "source": "one_pass_tool_route",
        }

    raw_content = str(response.get("content") or "").strip()
    legacy = _extract_json(raw_content)
    if legacy and (legacy.get("type") == "agent" or legacy.get("capabilities")):
        capabilities = validate_capabilities(legacy.get("capabilities"))
        if not capabilities:
            return _fallback(text, situational_context)
        goal = str(legacy.get("goal") or text).strip()[:500]
        if situational_context:
            goal = f"{goal}\n\n{situational_context}"
        return {
            "type": "agent", "capabilities": capabilities, "goal": goal,
            "confidence": _confidence(legacy.get("confidence")), "source": "legacy_json_route",
        }

    required = _required_capabilities(text, recent)
    if required:
        context_route = _read_context_fallback(text, required)
        if context_route is not None:
            return context_route
        goal = text if not situational_context else f"{text}\n\n{situational_context}"
        return {
            "type": "agent", "capabilities": required, "goal": goal,
            "confidence": None, "source": "forced_tool_guard",
        }

    content = _continue_truncated_reply(messages, response)
    if content:
        return {
            "type": "reply", "reply": content, "capabilities": [], "goal": text,
            "confidence": None, "source": "one_pass_reply",
        }
    return _fallback(text, situational_context)
