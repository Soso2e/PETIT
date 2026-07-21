"""Compatibility-preserving routing layer for explicit Notion reads.

The existing Agent implementation stays unchanged in ``agent_legacy``.  This
module only intercepts explicit read-only Notion requests, keeping normal chat,
project continuity, and all existing tool/write paths on the proven code path.
"""
from __future__ import annotations

import json
from typing import Any

from . import agent_legacy as _legacy

# Re-export the existing module surface, including compatibility helpers used by
# tests and other backend modules. The two functions below intentionally replace
# the legacy implementations after this copy.
for _export_name in dir(_legacy):
    if not _export_name.startswith("__"):
        globals()[_export_name] = getattr(_legacy, _export_name)

_NOTION_SOURCE_MARKERS = ("notion", "ノーション")
_NOTION_READ_TERMS = (
    "から", "で検索", "で調べ", "で探", "内から", "内で", "を検索", "を調べ", "を探",
    "参照", "確認", "見て", "書いてある", "内容", "情報", "どんな感じ",
)


def _sync_legacy_globals() -> None:
    """Propagate monkey-patched dependencies before delegating to legacy code."""
    for name in (
        "config", "db", "model_router", "project_router", "recall", "situation", "tools",
        "chat_completion", "parse_schedule_date", "has_schedule_date_expression",
    ):
        if name in globals():
            setattr(_legacy, name, globals()[name])


def _notion_read_requested(message: str) -> bool:
    text = str(message or "").casefold()
    if not any(marker in text for marker in _NOTION_SOURCE_MARKERS):
        return False
    legacy_names = _legacy._related_tool_names(message)
    if "sync_notion_tasks" in legacy_names:
        return False
    return any(term.casefold() in text for term in _NOTION_READ_TERMS)


def _related_tool_names(message: str) -> list[str]:
    """Expose the new read tool without changing any legacy signal behavior."""
    names = list(_legacy._related_tool_names(message))
    if _notion_read_requested(message):
        names.append("search_notion")
    if "sync_notion_tasks" in names:
        names = [name for name in names if name != "search_notion"]
    return list(dict.fromkeys(names))


def _notion_fallback_reply(content: str) -> tuple[str, str]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return "Notion検索の結果を読み取れませんでした。", "invalid_result"
    if not isinstance(data, dict):
        return "Notion検索の結果を読み取れませんでした。", "invalid_result"

    status = str(data.get("status") or "error")
    query = str(data.get("query") or "指定内容")
    if status == "not_configured":
        return "Notion検索を使うには、PETIT側にNOTION_API_KEYを設定してください。", status
    if status == "invalid_query":
        return "Notionで探す語句を特定できませんでした。検索したい名前やテーマを入れてください。", status
    if status == "not_found":
        return f"Notionで「{query}」を検索しましたが、共有済みページには見つかりませんでした。", status
    if status == "error":
        error = str(data.get("error") or "Notion APIとの通信に失敗しました。")
        return f"Notion検索に失敗しました。{error}", status

    lines = [f"Notionで「{query}」に関するページを{int(data.get('count') or 0)}件見つけました。"]
    for item in (data.get("results") or [])[:3]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "タイトルなし")
        updated = str(item.get("last_edited_time") or "更新日時不明")
        excerpt = " ".join(str(item.get("excerpt") or "").split())[:240]
        url = str(item.get("url") or "")
        lines.append(f"- {title}（更新: {updated}）")
        if excerpt:
            lines.append(f"  {excerpt}")
        if url:
            lines.append(f"  {url}")
    return "\n".join(lines), status


def _run_notion_read(user_message: str, history: list[dict[str, str]] | None) -> dict[str, Any]:
    args = {"query": user_message, "limit": 3, "max_chars": 1200}
    content = tools.dispatch("search_notion", args)
    fallback_reply, status = _notion_fallback_reply(content)
    used_tools = [{"name": "search_notion", "arguments": json.dumps(args, ensure_ascii=False)}]

    if status != "found":
        return {
            "reply": fallback_reply,
            "used_tools": used_tools,
            "persist": not _tool_failed(content),
            "model_route": {
                "kind": "forced_read",
                "requested_route": "deterministic",
                "actual_route": "deterministic",
                "fallback_reason": f"notion_{status}",
                "model": None,
                "base_url_id": None,
                "tools": ["search_notion"],
            },
        }

    messages: list[dict[str, Any]] = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}]
    messages.extend(history or [])
    messages.append(_tool_result_message(user_message, [{"name": "search_notion", "content": content}]))
    try:
        answer, actual, fallback_reason = _complete(
            messages, tools_schema=None, route="agent", allow_chat_fallback=True
        )
        model = config.CHAT_MODEL if actual == "chat_fallback" else config.AGENT_MODEL
        route = "chat" if actual == "chat_fallback" else "agent"
        reply = _answer(answer, messages, model, route) or fallback_reply
        model_route = _route_meta("agent", actual, ["search_notion"], fallback_reason) | {"kind": "forced_read"}
    except LMStudioError:
        reply = fallback_reply
        model_route = {
            "kind": "forced_read",
            "requested_route": "agent",
            "actual_route": "deterministic",
            "fallback_reason": "models_unavailable",
            "model": None,
            "base_url_id": None,
            "tools": ["search_notion"],
        }
    return {
        "reply": reply,
        "used_tools": used_tools,
        "persist": not _tool_failed(content),
        "model_route": model_route,
    }


def run(
    user_message: str,
    history: list[dict[str, str]] | None = None,
    *,
    allow_defer: bool = True,
) -> dict[str, Any]:
    _sync_legacy_globals()
    if not _notion_read_requested(user_message):
        return _legacy.run(user_message, history=history, allow_defer=allow_defer)

    recent_history = _legacy._recent_history(history)
    project_turn = project_router.try_handle_project_turn(
        user_message,
        user_id=config.PETIT_OWNER_ID,
        recent_history=recent_history,
    )
    if project_turn:
        return project_turn
    return _run_notion_read(user_message, recent_history)
