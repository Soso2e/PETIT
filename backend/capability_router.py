"""One-pass conversation entry and capability selection for PETIT."""
from __future__ import annotations

import json
import re
from typing import Any

from . import config, time_context, tools
from .lmstudio_client import LMStudioError, chat_completion

CAPABILITY_GROUPS: dict[str, tuple[str, ...]] = {
    "lists_and_tasks": (
        "get_lists",
        "get_list_items",
        "create_list",
        "add_list_item",
        "get_tasks",
        "create_task",
        "update_task",
        "set_task_parent",
        "complete_task",
        "get_task_sync_status",
        "retry_task_sync",
        "sync_notion_tasks",
    ),
    "calendar": (
        "get_current_time",
        "get_schedule",
        "add_schedule",
        "sync_calendar",
        "create_reminder",
        "get_reminders",
        "manage_reminder",
        "get_weather",
    ),
    "knowledge": (
        "search_memory",
        "search_brain_notes",
        "search_notion",
        "edit_brain_note",
        "sync_obsidian_vault",
    ),
    "github": (
        "review_github_activity",
        "sync_github_evidence",
        "get_github_repository_candidates",
        "link_github_repository_candidate",
        "ignore_github_repository_candidate",
        "inspect_github_repository",
    ),
    "web": (
        "search_news",
        "start_background_research",
    ),
    "memory": (
        "save_memory",
        "summarize_now",
        "create_daily_briefing",
        "restore_context",
        "create_handoff_note",
    ),
    "projects": (
        "get_project_status",
        "get_tasks",
        "get_notion_project_candidates",
        "get_linkraft_project_candidates",
        "get_brain_note_candidates",
        "get_github_repository_candidates",
        "sync_notion_tasks",
        "sync_linkraft_projects",
        "sync_github_evidence",
    ),
    # Internal-only fallback. It is never advertised to the selector and exposes
    # explicit read operations only, so a routing failure cannot propose writes.
    "fallback_read": (
        "get_lists",
        "get_list_items",
        "get_tasks",
        "get_task_sync_status",
        "get_current_time",
        "get_schedule",
        "get_reminders",
        "get_weather",
        "search_memory",
        "search_brain_notes",
        "search_notion",
        "review_github_activity",
        "inspect_github_repository",
        "search_news",
        "get_project_status",
        "get_notion_project_candidates",
        "get_linkraft_project_candidates",
        "get_brain_note_candidates",
        "get_github_repository_candidates",
    ),
}

_GROUP_DESCRIPTIONS = {
    "lists_and_tasks": "タスク、Notionタスク、親子関係、任意リストの取得・追加・変更",
    "calendar": "時刻、天気、予定、リマインダー、カレンダーの取得・追加・変更・同期",
    "knowledge": "BRAIN、Notion、記憶の検索と確認付き編集",
    "github": "GitHubのリポジトリ、差分、PR、開発状況",
    "web": "ニュースや外部調査",
    "memory": "長期記憶、要約、復帰、引き継ぎ、ブリーフィング",
    "projects": "PETIT内部プロジェクトと外部ソースの継続管理",
}

_ROUTABLE_GROUPS = tuple(_GROUP_DESCRIPTIONS)

_ROUTER_SYSTEM_PROMPT = """あなたはPETITの会話入口です。
会話文脈と依頼から、次のどちらかを選んでください。

- PETITのToolが不要なら、この場でユーザーへの最終回答を自然な日本語で返す。
- 個人データ、現在情報、外部ソースの参照、または操作が必要なら route_to_agent をcallする。

判断基準:
- 雑談、相談、説明、文章作成など、手元の会話だけで完結する依頼は直接回答する。
- タスク、予定、BRAIN、Notion、GitHub、記憶、ニュースなどの実データが必要なら推測で答えずrouteする。
- 話題提示だけから作成・追加・変更を推測しない。
- 書き込み意図は、追加・作成・変更・完了などが文脈上明確な場合だけ扱う。
- routeする場合は最大4グループと、Agentが達成すべき目的を渡す。
- Toolが必要な依頼に「調べます」「確認します」とだけ答えない。
"""

_ROUTE_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "route_to_agent",
        "description": (
            "PETITの個人データ、現在情報、外部ソース、または操作Toolが必要な依頼を"
            "Agent Runtimeへ引き渡す。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "capabilities": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(_ROUTABLE_GROUPS)},
                    "maxItems": 4,
                    "description": "Agentへ公開するCapabilityグループ",
                },
                "goal": {
                    "type": "string",
                    "description": "AgentがTool結果を使って達成する目的",
                },
                "confidence": {
                    "type": "number",
                    "description": "0.0から1.0の判断確信度",
                },
            },
            "required": ["capabilities", "goal"],
            "additionalProperties": False,
        },
    },
}


def _extract_json(content: str) -> dict[str, Any] | None:
    """Parse legacy JSON router output for backwards-compatible providers."""
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
    goal = text
    if context:
        goal = f"{goal}\n\n{context}"
    return {
        "type": "agent",
        "capabilities": ["fallback_read"],
        "goal": goal,
        "confidence": None,
        "source": "safe_fallback",
    }


def _route_arguments(message: dict[str, Any]) -> dict[str, Any] | None:
    for raw in message.get("tool_calls") or []:
        if not isinstance(raw, dict):
            continue
        function = raw.get("function") or {}
        if not isinstance(function, dict) or function.get("name") != "route_to_agent":
            continue
        arguments = function.get("arguments") or "{}"
        try:
            parsed = json.loads(arguments) if isinstance(arguments, str) else dict(arguments)
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def choose(user_message: str, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """Answer tool-free turns once, or route tool-dependent turns to Agent."""
    text = str(user_message or "").strip()
    recent = history or []
    runtime_context = time_context.prompt_context_for(text, history=recent)

    messages: list[dict[str, str]] = [
        {"role": "system", "content": _ROUTER_SYSTEM_PROMPT}
    ]
    for item in recent[-6:]:
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content[:1200]})

    user_content = text
    if runtime_context:
        user_content = f"{text}\n\n{runtime_context}"
    messages.append({"role": "user", "content": user_content})

    try:
        response = chat_completion(
            messages,
            tools=[_ROUTE_TOOL_SCHEMA],
            temperature=0.2,
            model=config.CHAT_MODEL,
            max_tokens=config.LIGHT_MAX_TOKENS,
            route="chat",
        )
    except LMStudioError:
        return _fallback(text, runtime_context)

    routed = _route_arguments(response)
    if routed is not None:
        capabilities = validate_capabilities(routed.get("capabilities"))
        if not capabilities:
            return _fallback(text, runtime_context)
        goal = str(routed.get("goal") or text).strip()[:500]
        if runtime_context:
            goal = f"{goal}\n\n{runtime_context}"
        return {
            "type": "agent",
            "capabilities": capabilities,
            "goal": goal,
            "confidence": _confidence(routed.get("confidence")),
            "source": "one_pass_tool_route",
        }

    content = str(response.get("content") or "").strip()
    legacy = _extract_json(content)
    if legacy and (
        legacy.get("type") == "agent" or legacy.get("capabilities")
    ):
        capabilities = validate_capabilities(legacy.get("capabilities"))
        if not capabilities:
            return _fallback(text, runtime_context)
        goal = str(legacy.get("goal") or text).strip()[:500]
        if runtime_context:
            goal = f"{goal}\n\n{runtime_context}"
        return {
            "type": "agent",
            "capabilities": capabilities,
            "goal": goal,
            "confidence": _confidence(legacy.get("confidence")),
            "source": "legacy_json_route",
        }

    if content:
        return {
            "type": "reply",
            "reply": content,
            "capabilities": [],
            "goal": text,
            "confidence": None,
            "source": "one_pass_reply",
        }

    return _fallback(text, runtime_context)
