"""Bounded context-driven Agent loop with resumable confirmation-gated writes."""
from __future__ import annotations

import json
from typing import Any

from . import agent_progress, agent_state, capability_router, config, request_context, tools
from .lmstudio_client import LMStudioError, chat_completion

_MAX_TOOL_CALLS = 6
_MAX_RESULT_CHARS = 5000
_MAX_HISTORY_MESSAGES = 8
_MAX_HISTORY_CHARS = 3200

_AGENT_SYSTEM_PROMPT = """あなたはPETIT。ユーザーの生活・制作・開発を支える実務的な相棒です。
直近の会話と元の依頼を読み、必要なToolを選び、結果を受け取ったら目的を満たしたか判断してください。

重要:
- 単語一致ではなく、会話文脈・対象・操作・質問か書き込みかを判断する。
- 元の依頼を最後まで保持する。
- 既に得た結果で答えられるなら追加Toolを使わず終了する。
- Tool結果にない外部事実を作らない。
- 書き込みはTool callとして提案する。実行と承認はランタイムが管理する。
- 「〜について」のような話題提示だけで、作成・追加・変更を推測しない。
- 対象が曖昧なら勝手に別概念へ変換せず、必要な確認を短く返す。
- 最終回答は自然な日本語。Markdownは使わない。
"""

_CONFIRMATION_LABELS = {
    "create_task": "タスクを作成",
    "add_task": "ローカルタスクを作成",
    "update_task": "タスクを変更",
    "complete_task": "タスクを完了",
    "create_list": "リストを作成",
    "add_list_item": "リストへ項目を追加",
    "add_schedule": "予定を追加",
    "save_memory": "長期記憶へ保存",
    "create_handoff_note": "引き継ぎメモを保存",
    "edit_brain_note": "BRAINノートを変更",
    "link_github_repository_candidate": "GitHubリポジトリをプロジェクトへ紐付け",
    "ignore_github_repository_candidate": "GitHubリポジトリ候補を無視",
}

_NOISE_KEYS = {
    "embedding",
    "embedding_model",
    "embedding_version",
    "metadata_json",
    "raw",
    "debug",
    "trace",
}


def _recent_history(history: list[dict[str, str]] | None) -> list[dict[str, str]]:
    clean: list[dict[str, str]] = []
    remaining = _MAX_HISTORY_CHARS
    for item in reversed((history or [])[-_MAX_HISTORY_MESSAGES:]):
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content or remaining <= 0:
            continue
        content = content[-remaining:]
        clean.append({"role": role, "content": content})
        remaining -= len(content)
    return list(reversed(clean))


def _normalize_tool_calls(message: dict[str, Any], round_number: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(message.get("tool_calls") or []):
        if not isinstance(raw, dict):
            continue
        function = raw.get("function") or {}
        if not isinstance(function, dict):
            continue
        name = str(function.get("name") or "").strip()
        arguments = function.get("arguments", "{}")
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments or {}, ensure_ascii=False)
        result.append(
            {
                "id": str(raw.get("id") or f"petit_agent_{round_number}_{index}"),
                "name": name,
                "arguments": arguments,
            }
        )
    return result


def _selected_schemas(names: list[str]) -> list[dict[str, Any]]:
    allowed = set(names)
    return [
        item
        for item in tools.openai_tools_schema()
        if item.get("function", {}).get("name") in allowed
    ]


def _tool_failed(result: str) -> bool:
    if str(result or "").startswith("[error]"):
        return True
    try:
        data = json.loads(result)
    except (json.JSONDecodeError, TypeError):
        return False
    if not isinstance(data, dict):
        return False
    return bool(data.get("error")) or any(
        data.get(key) is False
        for key in ("ok", "created", "completed", "added", "saved", "updated")
    )


def _compact_value(value: Any, depth: int = 0) -> Any:
    if depth >= 4:
        if isinstance(value, (dict, list)):
            return "…"
        return value
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 32:
                compact["_truncated"] = True
                break
            if str(key) in _NOISE_KEYS:
                continue
            compact[str(key)] = _compact_value(item, depth + 1)
        return compact
    if isinstance(value, list):
        result = [_compact_value(item, depth + 1) for item in value[:20]]
        if len(value) > 20:
            result.append({"_remaining": len(value) - 20})
        return result
    if isinstance(value, str):
        normalized = " ".join(value.split())
        return normalized if len(normalized) <= 800 else normalized[:800] + "…"
    return value


def compact_tool_result(name: str, raw_result: str) -> str:
    """Remove transport noise while retaining facts needed by the next decision."""
    try:
        parsed = json.loads(raw_result)
    except (json.JSONDecodeError, TypeError):
        text = " ".join(str(raw_result or "").split())
        return text if len(text) <= _MAX_RESULT_CHARS else text[:_MAX_RESULT_CHARS] + "…"

    compact = _compact_value(parsed)
    rendered = json.dumps(
        {"tool": name, "result": compact},
        ensure_ascii=False,
        default=str,
    )
    return rendered if len(rendered) <= _MAX_RESULT_CHARS else rendered[:_MAX_RESULT_CHARS] + "…"


def _tool_result_context(original_request: str, results: list[dict[str, str]]) -> str:
    lines = [
        f"元の依頼: {original_request}",
        "以下は実行済みToolの圧縮結果です。目的を満たしたか判断し、不足時だけ次のToolを選んでください。",
    ]
    for item in results:
        lines.append(f"Tool: {item['name']}\nResult: {item['content']}")
    return "\n\n".join(lines)


def _answer(message: dict[str, Any], messages: list[dict[str, Any]]) -> str:
    content = str(message.get("content") or "").strip()
    if content:
        return content
    if message.get("_finish_reason") == "length":
        retry = chat_completion(
            messages,
            tools=None,
            model=config.AGENT_MODEL,
            route="agent",
        )
        return str(retry.get("content") or "").strip()
    return ""


def _confirmation_text(name: str, arguments: dict[str, Any]) -> str:
    label = _CONFIRMATION_LABELS.get(name, name)
    visible = {
        key: value
        for key, value in arguments.items()
        if value not in (None, "", [], {}) and not str(key).startswith("_")
    }
    details = "\n".join(f"- {key}: {value}" for key, value in visible.items())
    suffix = f"\n{details}" if details else ""
    return f"書き込み前に確認します。\n操作: {label}{suffix}\nこの内容で実行しますか？"


def _route_meta(
    capabilities: list[str],
    selected_names: list[str],
    *,
    router_source: str,
    router_confidence: float | None,
    tool_rounds: int,
    total_tool_calls: int,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "kind": "agent",
        "requested_route": "agent",
        "actual_route": "agent",
        "model": config.AGENT_MODEL,
        "base_url_id": "agent",
        "tools": selected_names,
        "capabilities": capabilities,
        "router_source": router_source,
        "router_confidence": router_confidence,
        "tool_rounds": tool_rounds,
        "total_tool_calls": total_tool_calls,
        "fallback_reason": fallback_reason,
    }


def _save_resume_state(
    *,
    original_request: str,
    messages: list[dict[str, Any]],
    capabilities: list[str],
    selected_names: list[str],
    attempted: set[tuple[str, str]],
    tool_rounds: int,
    total_tool_calls: int,
    used_tools: list[dict[str, Any]],
) -> str:
    request_id, session_id = request_context.current_ids()
    return agent_state.save(
        {
            "original_request": original_request,
            "messages": messages,
            "capabilities": capabilities,
            "selected_names": selected_names,
            "attempted": [list(item) for item in attempted],
            "tool_rounds": tool_rounds,
            "total_tool_calls": total_tool_calls,
            "used_tools": used_tools,
            "request_id": request_id,
            "session_id": session_id,
        }
    )


def _execute_loop(
    *,
    original_request: str,
    messages: list[dict[str, Any]],
    capabilities: list[str],
    selected_names: list[str],
    attempted: set[tuple[str, str]] | None = None,
    tool_rounds: int = 0,
    total_tool_calls: int = 0,
    used_tools: list[dict[str, Any]] | None = None,
    router_source: str = "llm",
    router_confidence: float | None = None,
    allow_write_proposal: bool = True,
) -> dict[str, Any]:
    attempted = attempted or set()
    used_tools = list(used_tools or [])
    selected_schemas = _selected_schemas(selected_names)
    allowed = set(selected_names)
    had_failure = False

    while True:
        message = chat_completion(
            messages,
            tools=selected_schemas or None,
            model=config.AGENT_MODEL,
            route="agent",
        )
        calls = _normalize_tool_calls(message, tool_rounds + 1)
        if not calls:
            reply = _answer(message, messages)
            if not reply:
                reply = "うまく答えを確定できなかったよ。対象やしてほしいことを少し具体的に教えて。"
            agent_progress.emit("finalizing", "返答をまとめてるよ")
            return {
                "reply": reply,
                "used_tools": used_tools,
                "persist": not had_failure,
                "model_route": _route_meta(
                    capabilities,
                    selected_names,
                    router_source=router_source,
                    router_confidence=router_confidence,
                    tool_rounds=tool_rounds,
                    total_tool_calls=total_tool_calls,
                ),
            }

        if tool_rounds >= config.MAX_TOOL_ITERATIONS:
            return {
                "reply": "必要な確認が多段になったため、ここで停止したよ。対象を少し絞ってもう一度頼んで。",
                "used_tools": used_tools,
                "persist": False,
                "model_route": _route_meta(
                    capabilities,
                    selected_names,
                    router_source=router_source,
                    router_confidence=router_confidence,
                    tool_rounds=tool_rounds,
                    total_tool_calls=total_tool_calls,
                    fallback_reason="tool_iteration_limit",
                ),
            }
        tool_rounds += 1

        round_results: list[dict[str, str]] = []
        for call in calls:
            if total_tool_calls >= _MAX_TOOL_CALLS:
                return {
                    "reply": "確認するToolの上限に達したため、ここで停止したよ。対象を絞ってもう一度頼んで。",
                    "used_tools": used_tools,
                    "persist": False,
                    "model_route": _route_meta(
                        capabilities,
                        selected_names,
                        router_source=router_source,
                        router_confidence=router_confidence,
                        tool_rounds=tool_rounds,
                        total_tool_calls=total_tool_calls,
                        fallback_reason="tool_call_limit",
                    ),
                }

            name = call["name"]
            if name not in allowed:
                had_failure = True
                round_results.append(
                    {
                        "name": name or "unknown",
                        "content": json.dumps(
                            {"error": "tool_not_allowed", "tool": name},
                            ensure_ascii=False,
                        ),
                    }
                )
                continue
            try:
                arguments = tools.parse_arguments(name, call["arguments"])
            except ValueError:
                had_failure = True
                round_results.append(
                    {
                        "name": name,
                        "content": json.dumps(
                            {"error": "invalid_tool_arguments", "tool": name},
                            ensure_ascii=False,
                        ),
                    }
                )
                continue

            signature_json = json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)
            signature = (name, signature_json)
            if signature in attempted:
                had_failure = True
                round_results.append(
                    {
                        "name": name,
                        "content": json.dumps(
                            {
                                "error": "duplicate_tool_call",
                                "tool": name,
                                "message": "同じ引数の再実行を停止しました。",
                            },
                            ensure_ascii=False,
                        ),
                    }
                )
                continue
            attempted.add(signature)
            total_tool_calls += 1

            if tools.requires_confirmation(name):
                if not allow_write_proposal:
                    round_results.append(
                        {
                            "name": name,
                            "content": json.dumps(
                                {
                                    "error": "additional_write_requires_new_confirmation",
                                    "tool": name,
                                },
                                ensure_ascii=False,
                            ),
                        }
                    )
                    continue
                resume_id = _save_resume_state(
                    original_request=original_request,
                    messages=messages,
                    capabilities=capabilities,
                    selected_names=selected_names,
                    attempted=attempted,
                    tool_rounds=tool_rounds,
                    total_tool_calls=total_tool_calls,
                    used_tools=used_tools,
                )
                return {
                    "reply": _confirmation_text(name, arguments),
                    "used_tools": used_tools,
                    "pending_actions": [
                        {
                            "name": "execute_agent_write",
                            "arguments": {
                                "resume_id": resume_id,
                                "tool_name": name,
                                "tool_arguments": arguments,
                            },
                        }
                    ],
                    "persist": True,
                    "model_route": _route_meta(
                        capabilities,
                        selected_names,
                        router_source=router_source,
                        router_confidence=router_confidence,
                        tool_rounds=tool_rounds,
                        total_tool_calls=total_tool_calls,
                    )
                    | {"pending_write_tool": name},
                }

            agent_progress.tool_started(name, arguments)
            raw_result = tools.dispatch(name, arguments)
            failed = _tool_failed(raw_result)
            agent_progress.tool_finished(name, ok=not failed)
            had_failure = had_failure or failed
            used_tools.append({"name": name, "arguments": signature_json})
            round_results.append(
                {"name": name, "content": compact_tool_result(name, raw_result)}
            )

        messages.append(
            {
                "role": "assistant",
                "content": "必要な情報をToolで確認しました。結果を踏まえて続けます。",
            }
        )
        messages.append(
            {
                "role": "user",
                "content": _tool_result_context(original_request, round_results),
            }
        )


def run(user_message: str, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """Route from context, then execute a bounded Tool loop."""
    original_request = str(user_message or "").strip()
    recent = _recent_history(history)
    agent_progress.emit("planning", "要望に必要な情報を整理してるよ")
    route = capability_router.choose(original_request, recent)
    if route.get("type") == "reply":
        return {
            "reply": str(route.get("reply") or "").strip(),
            "used_tools": [],
            "persist": True,
            "model_route": {
                "kind": "chat",
                "requested_route": "chat",
                "actual_route": "chat",
                "model": config.CHAT_MODEL,
                "base_url_id": "chat",
                "tools": [],
                "capabilities": [],
                "router_source": route.get("source"),
                "router_confidence": route.get("confidence"),
            },
        }

    capabilities = list(route.get("capabilities") or [])
    selected_names = capability_router.tool_names_for(capabilities)
    messages: list[dict[str, Any]] = [{"role": "system", "content": _AGENT_SYSTEM_PROMPT}]
    messages.extend(recent)
    messages.append(
        {
            "role": "user",
            "content": (
                f"元の依頼: {original_request}\n"
                f"今回の目的: {route.get('goal') or original_request}\n"
                "この目的に直接答えてください。"
            ),
        }
    )
    return _execute_loop(
        original_request=original_request,
        messages=messages,
        capabilities=capabilities,
        selected_names=selected_names,
        router_source=str(route.get("source") or "fallback"),
        router_confidence=route.get("confidence"),
    )


def resume_after_write(
    state: dict[str, Any],
    tool_name: str,
    tool_arguments: dict[str, Any],
    raw_result: str,
) -> str:
    """Return an approved write result to the Agent and produce a natural final reply."""
    original_request = str(state.get("original_request") or "")
    messages = list(state.get("messages") or [])
    request_id = state.get("request_id")
    session_id = state.get("session_id")
    agent_progress.emit(
        "tool_finished",
        "書き込みが完了したよ。返答をまとめてるよ",
        tool=tool_name,
        request_id=request_id,
        session_id=session_id,
    )
    messages.append(
        {
            "role": "assistant",
            "content": "ユーザーが書き込み内容を確認し、実行されました。",
        }
    )
    messages.append(
        {
            "role": "user",
            "content": (
                f"元の依頼: {original_request}\n"
                f"実行したTool: {tool_name}\n"
                f"引数: {json.dumps(tool_arguments, ensure_ascii=False, default=str)}\n"
                f"実行結果: {compact_tool_result(tool_name, raw_result)}\n"
                "結果を自然な日本語で簡潔に伝えてください。必要なら読み取りToolで確認して構いません。"
            ),
        }
    )

    capabilities = list(state.get("capabilities") or [])
    selected_names = [
        name
        for name in capability_router.tool_names_for(capabilities)
        if not tools.requires_confirmation(name)
    ]
    try:
        result = _execute_loop(
            original_request=original_request,
            messages=messages,
            capabilities=capabilities,
            selected_names=selected_names,
            attempted={tuple(item) for item in state.get("attempted") or [] if len(item) == 2},
            tool_rounds=int(state.get("tool_rounds") or 0),
            total_tool_calls=int(state.get("total_tool_calls") or 0),
            used_tools=list(state.get("used_tools") or [])
            + [
                {
                    "name": tool_name,
                    "arguments": json.dumps(tool_arguments, ensure_ascii=False, default=str),
                }
            ],
            router_source="resume",
            router_confidence=None,
            allow_write_proposal=False,
        )
        return str(result.get("reply") or "").strip() or "確認された内容を実行したよ。"
    except LMStudioError:
        return "確認された内容を実行したよ。"
