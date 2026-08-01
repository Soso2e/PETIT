"""Capability selection for PETIT's agent-first bounded runtime."""
from __future__ import annotations

import json
import re
from typing import Any

from . import config, tools
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
}

_GROUP_DESCRIPTIONS = {
    "lists_and_tasks": "タスク、Notionタスク、任意リスト、その項目の取得・追加・変更",
    "calendar": "時刻、天気、予定、カレンダーの取得・追加・同期",
    "knowledge": "BRAIN、Notion、記憶の検索と確認付き編集",
    "github": "GitHubのリポジトリ、差分、PR、開発状況",
    "web": "ニュースや外部調査",
    "memory": "長期記憶、要約、復帰、引き継ぎ、ブリーフィング",
    "projects": "PETIT内部プロジェクトと外部ソースの継続管理",
}

_ROUTER_SYSTEM_PROMPT = """あなたはPETITのCapability Selectorです。会話文脈から、Agentへ公開するCapabilityだけを選び、JSONだけを返してください。
単語一致ではなく、直前の会話・対象・操作・質問か書き込みかを考えてください。

返却形式:
{"capabilities":["group"],"goal":"Agentが達成すべき目的","confidence":0.0}

通常の雑談やTool不要の会話ではcapabilitiesを空配列にしてください。最終返答は必ずAgentが生成するため、返答本文は作らないでください。

利用可能なCapability:
%s

ルール:
- 最大4グループまで。
- Tool名や引数は返さない。
- 「〜について」のような話題提示だけで、作成や追加を推測しない。
- 書き込み意図は、追加・作成・変更・完了などが文脈上明確な場合だけ扱う。
- 不明瞭でも勝手な書き込みを選ばず、必要な読み取りCapabilityだけを選ぶ。
- Toolが不要なら空配列にする。
- Markdownは禁止。""" % "\n".join(
    f"- {name}: {_GROUP_DESCRIPTIONS[name]}" for name in CAPABILITY_GROUPS
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
        if name in CAPABILITY_GROUPS and name not in result:
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


def choose(user_message: str, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """Select bounded capability groups while keeping final generation on Agent."""
    text = str(user_message or "").strip()
    messages: list[dict[str, str]] = [{"role": "system", "content": _ROUTER_SYSTEM_PROMPT}]
    for item in (history or [])[-6:]:
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content[:1200]})
    messages.append({"role": "user", "content": text})

    try:
        response = chat_completion(
            messages,
            tools=None,
            temperature=0.2,
            model=config.CHAT_MODEL,
            max_tokens=256,
            route="chat",
        )
        parsed = _extract_json(response.get("content") or "")
    except LMStudioError:
        parsed = None

    if not parsed:
        return {
            "type": "agent",
            "capabilities": [],
            "goal": text,
            "confidence": None,
            "source": "fallback",
        }

    capabilities = validate_capabilities(parsed.get("capabilities"))
    return {
        "type": "agent",
        "capabilities": capabilities,
        "goal": str(parsed.get("goal") or text).strip()[:500],
        "confidence": _confidence(parsed.get("confidence")),
        "source": "llm",
    }
