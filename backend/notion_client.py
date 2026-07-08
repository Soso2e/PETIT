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


def _patch(path: str, body: dict[str, Any], timeout: float = 15) -> dict[str, Any]:
    try:
        resp = httpx.patch(f"{_BASE}{path}", json=body, headers=_headers(), timeout=timeout)
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


def _extract_multi_select(prop: dict[str, Any] | None) -> list[str]:
    if prop is None:
        return []
    items = prop.get("multi_select") or []
    return [item.get("name", "") for item in items if item.get("name")]


def _parse_page(page: dict[str, Any]) -> dict[str, Any]:
    """Convert a Notion page object to a flat task dict."""
    props = page.get("properties", {})
    title = _extract_text(props.get(config.NOTION_PROP_TITLE))
    status = _extract_select(props.get(config.NOTION_PROP_STATUS))
    due = _extract_date(props.get(config.NOTION_PROP_DUE))
    priority = _extract_select(props.get(config.NOTION_PROP_PRIORITY))
    categories = _extract_multi_select(props.get(config.NOTION_PROP_CATEGORY))
    reason = _extract_text(props.get(config.NOTION_PROP_REASON))
    done = _extract_date(props.get(config.NOTION_PROP_DONE))
    return {
        "external_id": page.get("id", ""),
        "title": title,
        "status": status or "unknown",
        "due_date": due,
        "priority": priority or None,
        "category": ", ".join(categories) if categories else None,
        "reason": reason or None,
        "done_date": done,
        "url": page.get("url", ""),
    }


def _title_prop(value: str) -> dict[str, Any]:
    return {"title": [{"text": {"content": value}}]}


def _rich_text_prop(value: str) -> dict[str, Any]:
    return {"rich_text": [{"text": {"content": value}}]} if value else {"rich_text": []}


def _date_prop(value: str | None) -> dict[str, Any]:
    if not value:
        return {"date": None}
    return {"date": {"start": value}}


def _select_prop(value: str | None) -> dict[str, Any]:
    if not value:
        return {"select": None}
    return {"select": {"name": value}}


def _status_prop(value: str | None) -> dict[str, Any]:
    if not value:
        return {"status": None}
    return {"status": {"name": value}}


def _multi_select_prop(values: list[str] | None) -> dict[str, Any]:
    return {"multi_select": [{"name": value} for value in (values or []) if value]}


def _task_properties(
    title: str | None = None,
    status: str | None = None,
    due_date: str | None = None,
    priority: str | None = None,
    categories: list[str] | None = None,
    reason: str | None = None,
    done_date: str | None = None,
) -> dict[str, Any]:
    props: dict[str, Any] = {}
    if title is not None:
        props[config.NOTION_PROP_TITLE] = _title_prop(title)
    if status is not None:
        props[config.NOTION_PROP_STATUS] = _status_prop(status)
    if due_date is not None:
        props[config.NOTION_PROP_DUE] = _date_prop(due_date)
    if priority is not None:
        props[config.NOTION_PROP_PRIORITY] = _select_prop(priority)
    if categories is not None:
        props[config.NOTION_PROP_CATEGORY] = _multi_select_prop(categories)
    if reason is not None:
        props[config.NOTION_PROP_REASON] = _rich_text_prop(reason)
    if done_date is not None:
        props[config.NOTION_PROP_DONE] = _date_prop(done_date)
    return props


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


def create_task_page(
    title: str,
    due_date: str | None = None,
    priority: str | None = None,
    categories: list[str] | None = None,
    reason: str | None = None,
    status: str | None = None,
    db_id: str | None = None,
) -> dict[str, Any]:
    """Create one task page in the configured Notion task database."""
    db_id = db_id or config.NOTION_TASKS_DB_ID
    body = {
        "parent": {"database_id": db_id},
        "properties": _task_properties(
            title=title,
            status=status or config.NOTION_DEFAULT_STATUS,
            due_date=due_date,
            priority=priority,
            categories=categories,
            reason=reason,
        ),
    }
    return _parse_page(_post("/pages", body, timeout=20))


def update_task_page(
    page_id: str,
    status: str | None = None,
    due_date: str | None = None,
    priority: str | None = None,
    categories: list[str] | None = None,
    reason: str | None = None,
    done_date: str | None = None,
) -> dict[str, Any]:
    """Update task page properties and return the parsed task."""
    props = _task_properties(
        status=status,
        due_date=due_date,
        priority=priority,
        categories=categories,
        reason=reason,
        done_date=done_date,
    )
    if not props:
        raise NotionError("更新する Notion プロパティがありません。")
    return _parse_page(_patch(f"/pages/{page_id}", {"properties": props}, timeout=20))
