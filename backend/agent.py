"""Compatibility-preserving routing layer for explicit read-only source requests.

The existing Agent implementation stays unchanged in ``agent_legacy``. This
module intercepts explicit Notion reads and cross-repository GitHub reviews,
keeping normal chat, project continuity, and all existing write paths on the
proven code path.
"""
from __future__ import annotations

import json
from typing import Any

from . import agent_legacy as _legacy

# Re-export the existing module surface, including compatibility helpers used by
# tests and other backend modules. The functions below intentionally replace the
# legacy implementations after this copy.
for _export_name in dir(_legacy):
    if not _export_name.startswith("__"):
        globals()[_export_name] = getattr(_legacy, _export_name)

# Keep recurring prompts compact because they are sent on every model request.
CHAT_SYSTEM_PROMPT = (
    "あなたはPETIT。自然で短い日本語を1〜2文で返す。"
    "Markdownは使わず、質問に直接答える。"
)
AGENT_SYSTEM_PROMPT = (
    "あなたはPETIT。結論から、必要に応じて十分な長さの日本語で答える。Markdownは使わない。"
    "事実と判断を分け、外部情報はツール結果だけを使う。"
    "書き込みは実行結果なしに完了と言わない。"
)
SYSTEM_PROMPT = AGENT_SYSTEM_PROMPT
_legacy.CHAT_SYSTEM_PROMPT = CHAT_SYSTEM_PROMPT
_legacy.AGENT_SYSTEM_PROMPT = AGENT_SYSTEM_PROMPT
_legacy.SYSTEM_PROMPT = SYSTEM_PROMPT

# Install task-edit signals before the background worker starts. This keeps
# natural phrasing deterministic instead of relying only on the lightweight
# model router.
_TASK_TOOL_SIGNALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "update_task",
        (
            "タスクを編集", "タスクを変更", "タスク名を変更", "期限を変更",
            "優先度を変更", "締切を変", "締切を延ば", "日付を変",
            "内容を変更", "メモを変更", "エリアを変更", "プロジェクトを変更",
            "未完了に戻",
        ),
    ),
    (
        "retry_task_sync",
        ("タスク同期を再試行", "Notion同期を再試行", "同期をやり直"),
    ),
    (
        "get_task_sync_status",
        ("タスク同期状態", "タスクの同期状況", "同期エラー", "同期の失敗理由"),
    ),
)
_existing_signal_names = {name for name, _signals in _TOOL_SIGNALS}
_TOOL_SIGNALS = tuple(_TOOL_SIGNALS) + tuple(
    item for item in _TASK_TOOL_SIGNALS if item[0] not in _existing_signal_names
)
_legacy._TOOL_SIGNALS = _TOOL_SIGNALS

_NOTION_SOURCE_MARKERS = ("notion", "ノーション")
_NOTION_READ_TERMS = (
    "から", "で検索", "で調べ", "で探", "内から", "内で", "を検索", "を調べ", "を探",
    "参照", "確認", "見て", "書いてある", "内容", "情報", "どんな感じ",
)
_GITHUB_SOURCE_MARKERS = ("github", "ギットハブ")
_GITHUB_REVIEW_TERMS = (
    "全リポジトリ", "全repository", "github全体", "開発差分", "前回差分",
    "差分レビュー", "新コミット", "新しいコミット", "最近のコミット",
    "開発を追", "開発状況", "朝レビュー", "githubレビュー",
)
_GITHUB_MAPPING_TERMS = ("候補", "紐付け", "ひも付け", "登録", "無視", "リンク")


def _sync_legacy_globals() -> None:
    """Propagate monkey-patched and dynamically installed dependencies."""
    for name in (
        "config", "db", "model_router", "project_router", "recall", "situation", "tools",
        "chat_completion", "parse_schedule_date", "has_schedule_date_expression", "_TOOL_SIGNALS",
    ):
        if name in globals():
            setattr(_legacy, name, globals()[name])


def _notion_read_requested(message: str) -> bool:
    _legacy._TOOL_SIGNALS = _TOOL_SIGNALS
    text = str(message or "").casefold()
    if not any(marker in text for marker in _NOTION_SOURCE_MARKERS):
        return False
    legacy_names = _legacy._related_tool_names(message)
    if "sync_notion_tasks" in legacy_names:
        return False
    return any(term.casefold() in text for term in _NOTION_READ_TERMS)


def _github_review_requested(message: str) -> bool:
    text = str(message or "").casefold()
    if not any(marker in text for marker in _GITHUB_SOURCE_MARKERS):
        return False
    if any(term.casefold() in text for term in _GITHUB_MAPPING_TERMS):
        return False
    if "githubを同期" in text or "githubの進捗を同期" in text or "github evidence" in text:
        return False
    return any(term.casefold() in text for term in _GITHUB_REVIEW_TERMS)


def _related_tool_names(message: str) -> list[str]:
    """Expose explicit read tools without changing legacy signal behavior."""
    _legacy._TOOL_SIGNALS = _TOOL_SIGNALS
    names = list(_legacy._related_tool_names(message))
    if _notion_read_requested(message):
        names.append("search_notion")
    if _github_review_requested(message):
        names.append("review_github_activity")
    if "sync_notion_tasks" in names:
        names = [name for name in names if name != "search_notion"]
    if any(name in names for name in ("update_task", "retry_task_sync", "get_task_sync_status")):
        names = [name for name in names if name != "get_tasks"]
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


def _github_review_reply(content: str) -> tuple[str, str, str]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return "GitHub差分レビューの結果を読み取れませんでした。", "invalid_result", "template"
    if not isinstance(data, dict):
        return "GitHub差分レビューの結果を読み取れませんでした。", "invalid_result", "template"
    status = str(data.get("status") or "error")
    kind = str(data.get("kind") or "template")
    message = str(data.get("message") or "").strip()
    if message:
        return message, status, kind
    if status == "not_configured":
        return "GitHub差分レビューを使うにはPETIT_GITHUB_TOKENを設定してください。", status, kind
    if status == "disabled":
        return "GitHub朝レビューは無効です。", status, kind
    return "GitHub差分レビューを作成できませんでした。", status, kind


def _run_github_review(user_message: str) -> dict[str, Any]:
    text = user_message.casefold()
    force = any(term in text for term in ("最新", "更新して", "今すぐ", "再取得", "もう一度"))
    args = {"force": force}
    content = tools.dispatch("review_github_activity", args)
    reply, status, kind = _github_review_reply(content)
    used_model = kind == "llm"
    return {
        "reply": reply,
        "used_tools": [{"name": "review_github_activity", "arguments": json.dumps(args, ensure_ascii=False)}],
        "persist": status not in {"error", "invalid_result"},
        "model_route": {
            "kind": "forced_read",
            "requested_route": "deterministic",
            "actual_route": "agent" if used_model else "deterministic",
            "fallback_reason": f"github_review_{status}" if not used_model else None,
            "model": config.AGENT_MODEL if used_model else None,
            "base_url_id": "agent" if used_model else None,
            "tools": ["review_github_activity"],
        },
    }


def run(
    user_message: str,
    history: list[dict[str, str]] | None = None,
    *,
    allow_defer: bool = True,
) -> dict[str, Any]:
    _sync_legacy_globals()
    notion_read = _notion_read_requested(user_message)
    github_review = _github_review_requested(user_message)
    if not notion_read and not github_review:
        return _legacy.run(user_message, history=history, allow_defer=allow_defer)

    recent_history = _legacy._recent_history(history)
    project_turn = project_router.try_handle_project_turn(
        user_message,
        user_id=config.PETIT_OWNER_ID,
        recent_history=recent_history,
    )
    if project_turn:
        return project_turn
    if github_review:
        return _run_github_review(user_message)
    return _run_notion_read(user_message, recent_history)
