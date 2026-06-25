"""Notion REST API client for PETIT.

Uses the public Notion API v1 directly (no SDK dependency).
Reference: https://developers.notion.com/reference/intro
"""
from __future__ import annotations

from typing import Any

import httpx

from . import config

_BASE = "https://api.notion.com/v1"
_NOTION_VERSION = "2022-06-28"


class NotionError(RuntimeError):
    """Raised on connection or API errors."""


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.NOTION_API_KEY}",
        "Notion-Version": _NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _get(path: str, timeout: float = 15) -> dict[str, Any]:
    try:
        resp = httpx.get(f"{_BASE}{path}", headers=_headers(), timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError as exc:
        raise NotionError("Notion API に接続できませんでした。ネットワークを確認してください。") from exc
    except httpx.HTTPStatusError as exc:
        raise NotionError(
            f"Notion API エラー {exc.response.status_code}: {exc.response.text[:300]}"
        ) from exc
    except httpx.HTTPError as exc:
        raise NotionError(f"Notion との通信に失敗しました: {exc}") from exc


def _post(path: str, body: dict[str, Any], timeout: float = 15) -> dict[str, Any]:
    try:
        resp = httpx.post(f"{_BASE}{path}", json=body, headers=_headers(), timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except httpx.ConnectError as exc:
        raise NotionError("Notion API に接続できませんでした。ネットワークを確認してください。") from exc
    except httpx.HTTPStatusError as exc:
        raise NotionError(
            f"Notion API エラー {exc.response.status_code}: {exc.response.text[:300]}"
        ) from exc
    except httpx.HTTPError as exc:
        raise NotionError(f"Notion との通信に失敗しました: {exc}") from exc


# ---------------------------------------------------------------------------
# Property extraction helpers
# ---------------------------------------------------------------------------

def _extract_text(prop: dict[str, Any] | None) -> str:
    """Extract plain text from title / rich_text property."""
    if prop is None:
        return ""
    for kind in ("title", "rich_text"):
        items = prop.get(kind, [])
        if items:
            return "".join(t.get("plain_text", "") for t in items)
    return ""


def _extract_select(prop: dict[str, Any] | None) -> str:
    """Extract name from select or status property."""
    if prop is None:
        return ""
    for kind in ("select", "status"):
        val = prop.get(kind)
        if val and isinstance(val, dict):
            return val.get("name", "")
    return ""


def _extract_date(prop: dict[str, Any] | None) -> str | None:
    """Extract start date from a date property."""
    if prop is None:
        return None
    date_val = prop.get("date")
    if date_val and isinstance(date_val, dict):
        return date_val.get("start")
    return None


def _parse_page(page: dict[str, Any]) -> dict[str, Any]:
    """Convert a Notion page object to a flat task dict."""
    props = page.get("properties", {})
    title = _extract_text(props.get(config.NOTION_PROP_TITLE))
    status = _extract_select(props.get(config.NOTION_PROP_STATUS))
    due = _extract_date(props.get(config.NOTION_PROP_DUE))
    priority = _extract_select(props.get(config.NOTION_PROP_PRIORITY))
    return {
        "external_id": page.get("id", ""),
        "title": title,
        "status": status or "unknown",
        "due_date": due,
        "priority": priority or None,
        "url": page.get("url", ""),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def query_database(
    db_id: str | None = None,
    filter_payload: dict[str, Any] | None = None,
    sorts: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Fetch all pages from a Notion database, handling pagination.

    Returns a list of parsed task dicts (not raw Notion pages).
    Raises NotionError on failure.
    """
    db_id = db_id or config.NOTION_TASKS_DB_ID
    body: dict[str, Any] = {"page_size": 100}
    if filter_payload:
        body["filter"] = filter_payload
    if sorts:
        body["sorts"] = sorts

    results: list[dict[str, Any]] = []
    cursor: str | None = None

    while True:
        if cursor:
            body["start_cursor"] = cursor
        data = _post(f"/databases/{db_id}/query", body)
        for page in data.get("results", []):
            parsed = _parse_page(page)
            if parsed["title"]:  # skip empty/deleted pages
                results.append(parsed)
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    return results
