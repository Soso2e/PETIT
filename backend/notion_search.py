"""Bounded read-only Notion page search for conversational retrieval."""
from __future__ import annotations

import re
import unicodedata
from typing import Any
from urllib.parse import urlencode

from . import config, notion_client

_DEFAULT_LIMIT = 3
_MAX_LIMIT = 5
_DEFAULT_PAGE_CHARS = 1200
_MAX_PAGE_CHARS = 2400
_MAX_DEPTH = 2

_QUERY_PREFIX = re.compile(
    r"(?:notion|ノーション)\s*(?:から|で|内から|内で|内の|を|に)?\s*(.+?)"
    r"(?:に関する|について|の情報|があったら|があれば|を検索|を調べ|を探|を確認|"
    r"教えて|検索して|調べて|探して|確認して|見て|どんな感じ|$)",
    re.IGNORECASE,
)
_NOISE_PHRASES = (
    "Notion", "notion", "ノーション", "から", "内から", "内で", "で検索", "で調べて", "で探して",
    "に関する情報", "に関する", "について", "の情報", "あったら", "あれば", "今どんな感じか",
    "どんな感じ", "教えて", "検索して", "調べて", "探して", "確認して", "見て", "ください", "お願い",
)
_TEXT_BLOCK_TYPES = {
    "paragraph", "heading_1", "heading_2", "heading_3", "heading_4",
    "bulleted_list_item", "numbered_list_item", "toggle", "quote", "callout",
    "code", "to_do", "template", "synced_block",
}


def normalize_query(value: str) -> str:
    """Extract a compact search phrase from a natural Japanese request."""
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not text:
        return ""
    match = _QUERY_PREFIX.search(text)
    candidate = match.group(1).strip() if match else text
    for phrase in sorted(_NOISE_PHRASES, key=len, reverse=True):
        candidate = re.sub(re.escape(phrase), " ", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"[\s、。,.!?！？:：;；「」『』()（）\[\]【】]+", " ", candidate).strip()
    candidate = re.sub(r"^(?:を|が|は|に|で|の)+|(?:を|が|は|に|で|の)+$", "", candidate).strip()
    if candidate in {"何", "内容", "情報", "ページ"}:
        return ""
    return candidate[:100]


def _plain_text(items: Any) -> str:
    if not isinstance(items, list):
        return ""
    return "".join(str(item.get("plain_text") or "") for item in items if isinstance(item, dict)).strip()


def _property_value(prop: dict[str, Any]) -> str:
    prop_type = str(prop.get("type") or "")
    if prop_type in {"title", "rich_text"}:
        return _plain_text(prop.get(prop_type))
    if prop_type in {"select", "status"}:
        value = prop.get(prop_type)
        return str(value.get("name") or "") if isinstance(value, dict) else ""
    if prop_type == "multi_select":
        return ", ".join(str(item.get("name")) for item in prop.get("multi_select") or [] if item.get("name"))
    if prop_type == "date":
        value = prop.get("date")
        if not isinstance(value, dict):
            return ""
        start = str(value.get("start") or "")
        end = str(value.get("end") or "")
        return f"{start}〜{end}" if start and end else start
    if prop_type == "people":
        return ", ".join(
            str(item.get("name") or item.get("id") or "")
            for item in prop.get("people") or []
            if item.get("name") or item.get("id")
        )
    if prop_type == "relation":
        count = len(prop.get("relation") or [])
        return f"{count}件" if count else ""
    if prop_type == "checkbox":
        return "true" if prop.get("checkbox") else "false"
    if prop_type in {"number", "url", "email", "phone_number"}:
        value = prop.get(prop_type)
        return "" if value is None else str(value)
    if prop_type == "formula":
        value = prop.get("formula")
        if isinstance(value, dict):
            kind = str(value.get("type") or "")
            raw = value.get(kind)
            if kind == "date" and isinstance(raw, dict):
                return str(raw.get("start") or "")
            return "" if raw is None else str(raw)
    return ""


def _page_properties(page: dict[str, Any]) -> tuple[str, dict[str, str]]:
    title = ""
    values: dict[str, str] = {}
    for name, raw in (page.get("properties") or {}).items():
        if not isinstance(raw, dict):
            continue
        value = _property_value(raw).strip()
        if not value:
            continue
        values[str(name)] = value
        if raw.get("type") == "title" and not title:
            title = value
    return title or "タイトルなし", values


def _block_text(block: dict[str, Any]) -> str:
    block_type = str(block.get("type") or "")
    payload = block.get(block_type)
    if block_type in _TEXT_BLOCK_TYPES and isinstance(payload, dict):
        return _plain_text(payload.get("rich_text"))
    if block_type in {"child_page", "child_database"} and isinstance(payload, dict):
        return str(payload.get("title") or "")
    if block_type == "table_row" and isinstance(payload, dict):
        return " | ".join(_plain_text(cell) for cell in payload.get("cells") or [] if _plain_text(cell))
    if block_type == "equation" and isinstance(payload, dict):
        return str(payload.get("expression") or "")
    return ""


def _children(block_id: str, cursor: str | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {"page_size": 100}
    if cursor:
        params["start_cursor"] = cursor
    return notion_client._get(f"/blocks/{block_id}/children?{urlencode(params)}", timeout=20)  # noqa: SLF001


def _page_text(page_id: str, max_chars: int, *, depth: int = 0, remaining: list[int] | None = None) -> str:
    if depth > _MAX_DEPTH or max_chars <= 0:
        return ""
    budget = remaining if remaining is not None else [max_chars]
    parts: list[str] = []
    cursor: str | None = None
    while budget[0] > 0:
        data = _children(page_id, cursor)
        for block in data.get("results") or []:
            if not isinstance(block, dict) or budget[0] <= 0:
                continue
            text = _block_text(block).strip()
            if text:
                clipped = text[: budget[0]]
                parts.append(clipped)
                budget[0] -= len(clipped)
            if block.get("has_children") and budget[0] > 0:
                child = _page_text(str(block.get("id") or ""), max_chars, depth=depth + 1, remaining=budget)
                if child:
                    parts.append(child)
        if not data.get("has_more") or budget[0] <= 0:
            break
        cursor = data.get("next_cursor")
        if not cursor:
            break
    return "\n".join(part for part in parts if part).strip()


def _search_pages(query: str, limit: int) -> list[dict[str, Any]]:
    body = {
        "query": query,
        "filter": {"property": "object", "value": "page"},
        "sort": {"direction": "descending", "timestamp": "last_edited_time"},
        "page_size": min(max(limit * 2, limit), 10),
    }
    data = notion_client._post("/search", body, timeout=20)  # noqa: SLF001
    pages: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in data.get("results") or []:
        if not isinstance(item, dict) or item.get("object") != "page":
            continue
        page_id = str(item.get("id") or "")
        if not page_id or page_id in seen or item.get("archived") or item.get("in_trash"):
            continue
        seen.add(page_id)
        pages.append(item)
        if len(pages) >= limit:
            break
    return pages


def search(query: str, limit: int = _DEFAULT_LIMIT, max_chars: int = _DEFAULT_PAGE_CHARS) -> dict[str, Any]:
    normalized = normalize_query(query)
    limit = max(1, min(int(limit), _MAX_LIMIT))
    max_chars = max(200, min(int(max_chars), _MAX_PAGE_CHARS))
    base = {
        "ok": False,
        "searched": False,
        "query": normalized,
        "count": 0,
        "results": [],
        "scope": "pages_shared_with_notion_connection",
        "limits": {"pages": limit, "chars_per_page": max_chars},
    }
    if not config.NOTION_API_KEY:
        return base | {"status": "not_configured", "error": "NOTION_API_KEY が設定されていません。"}
    if not normalized:
        return base | {"status": "invalid_query", "error": None}

    try:
        pages = _search_pages(normalized, limit)
    except notion_client.NotionError as exc:
        return base | {"status": "error", "searched": True, "error": str(exc)[:300]}

    if not pages:
        return base | {"ok": True, "status": "not_found", "searched": True, "error": None}

    results: list[dict[str, Any]] = []
    for page in pages:
        title, properties = _page_properties(page)
        content_error: str | None = None
        try:
            body_text = _page_text(str(page.get("id") or ""), max_chars)
        except notion_client.NotionError as exc:
            body_text = ""
            content_error = str(exc)[:200]
        property_text = "\n".join(f"{name}: {value}" for name, value in properties.items())
        combined = "\n".join(part for part in (property_text, body_text) if part).strip()[:max_chars]
        results.append(
            {
                "title": title,
                "url": str(page.get("url") or ""),
                "last_edited_time": page.get("last_edited_time"),
                "properties": properties,
                "excerpt": combined,
                "content_error": content_error,
            }
        )

    return base | {
        "ok": True,
        "status": "found",
        "searched": True,
        "count": len(results),
        "results": results,
        "error": None,
    }
