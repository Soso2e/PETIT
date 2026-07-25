"""Deterministic conversation flow for listing and creating generic lists."""
from __future__ import annotations

import json
import re
from typing import Any

from . import tools

_NAMED_CREATE_PATTERNS = (
    re.compile(
        r"^(?P<name>.+?)(?:の)?(?:リスト|一覧)(?:を)?(?:新しく)?"
        r"(?:作りたい|作って(?:ほしい)?|作成したい|追加したい|追加して(?:ほしい)?)[。.!！?？]*$"
    ),
)
_GENERAL_LIST_PHRASES = (
    "新しくリスト作りたい",
    "新しいリストを作りたい",
    "リストを新しく作りたい",
    "新規リストを作りたい",
    "リスト増やしたい",
    "リストを増やしたい",
    "リスト作りたい",
    "どんなリストがある",
    "リスト一覧",
)
_FOLLOWUP_MARKERS = (
    "ほかに作る？",
    "ほかに作りますか",
    "他に作る？",
    "他に作りますか",
)
_NON_NAMES = frozenset(
    {
        "はい",
        "うん",
        "お願い",
        "作って",
        "作りたい",
        "ほしい",
        "ない",
        "いらない",
        "やめる",
        "キャンセル",
        "新しい",
        "新しく",
        "新規",
    }
)
_NON_NAME_KEYS = frozenset(
    re.sub(r"[\s　_・\-]+", "", item).casefold() for item in _NON_NAMES
)


def _clean_name(value: str) -> str:
    name = str(value or "").strip(" \t\r\n　、。,.!！?？『』「」\"'")
    for suffix in ("のリスト", "リスト", "一覧"):
        if name.endswith(suffix) and len(name) > len(suffix):
            name = name[: -len(suffix)].rstrip(" 　")
            break
    return name


def _normalize_name(value: str) -> str:
    return re.sub(r"[\s　_・\-]+", "", _clean_name(value)).casefold()


def _explicit_name(message: str) -> str | None:
    text = str(message or "").strip()
    for pattern in _NAMED_CREATE_PATTERNS:
        match = pattern.match(text)
        if not match:
            continue
        name = _clean_name(match.group("name"))
        if _normalize_name(name) in _NON_NAME_KEYS:
            return None
        return name or None
    return None


def _last_assistant_reply(history: list[dict[str, str]] | None) -> str:
    for item in reversed(history or []):
        if item.get("role") == "assistant":
            return str(item.get("content") or "")
    return ""


def _followup_name(
    message: str,
    history: list[dict[str, str]] | None,
) -> str | None:
    previous = _last_assistant_reply(history)
    if not any(marker in previous for marker in _FOLLOWUP_MARKERS):
        return None
    raw = str(message or "").strip()
    if not raw or len(raw) > 80 or "\n" in raw:
        return None
    if any(token in raw for token in ("追加して", "入れて", "見せて", "教えて", "何が")):
        return None
    name = _clean_name(raw)
    if not name or _normalize_name(name) in _NON_NAME_KEYS:
        return None
    return name


def _general_request(message: str) -> bool:
    compact = re.sub(r"[\s　、。,.!！?？]", "", str(message or ""))
    return any(re.sub(r"[\s　]", "", phrase) in compact for phrase in _GENERAL_LIST_PHRASES)


def _load_lists() -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    args: dict[str, Any] = {}
    content = tools.dispatch("get_lists", args)
    used_tools = [{"name": "get_lists", "arguments": json.dumps(args, ensure_ascii=False)}]
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None, used_tools
    if not isinstance(data, dict) or data.get("error"):
        return None, used_tools
    return data, used_tools


def _inventory_text(data: dict[str, Any]) -> str:
    labels: list[str] = []
    for item in data.get("lists") or []:
        if not isinstance(item, dict):
            continue
        display_name = str(item.get("display_name") or item.get("name") or "名称未設定")
        source_label = str(item.get("source_label") or "保存先不明")
        labels.append(f"{display_name}（{source_label}）")
    return "、".join(labels) if labels else "まだリストはない"


def _model_route(tools_used: list[str], reason: str) -> dict[str, Any]:
    return {
        "kind": "list_conversation",
        "requested_route": "deterministic",
        "actual_route": "deterministic",
        "model": None,
        "base_url_id": None,
        "tools": tools_used,
        "reasons": [reason],
    }


def try_handle_list_turn(
    message: str,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any] | None:
    """Handle generic-list discovery and safe creation proposals."""
    requested_name = _explicit_name(message) or _followup_name(message, history)
    if requested_name is None and not _general_request(message):
        return None

    data, used_tools = _load_lists()
    if data is None:
        return None

    inventory = _inventory_text(data)
    if requested_name is None:
        return {
            "reply": f"今は、{inventory}があるよ。ほかに作る？",
            "used_tools": used_tools,
            "persist": True,
            "model_route": _model_route(["get_lists"], "deterministic_list_inventory"),
        }

    normalized = _normalize_name(requested_name)
    existing = next(
        (
            item
            for item in data.get("lists") or []
            if isinstance(item, dict)
            and _normalize_name(str(item.get("name") or item.get("display_name") or "")) == normalized
        ),
        None,
    )
    if existing is not None:
        display_name = str(existing.get("display_name") or existing.get("name") or requested_name)
        source_label = str(existing.get("source_label") or "保存先不明")
        return {
            "reply": f"{display_name}（{source_label}）は、もうあるよ。",
            "used_tools": used_tools,
            "persist": True,
            "model_route": _model_route(["get_lists"], "deterministic_existing_list"),
        }

    create_args = {"name": requested_name}
    return {
        "reply": f"今は、{inventory}があるよ。新しく「{requested_name}リスト」を作る？",
        "used_tools": used_tools,
        "pending_actions": [{"name": "create_list", "arguments": create_args}],
        "persist": True,
        "model_route": _model_route(
            ["get_lists", "create_list"],
            "deterministic_list_create_proposal",
        ),
    }
