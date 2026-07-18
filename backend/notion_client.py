"""Notion REST API client for PETIT.

Uses the public Notion API v1 directly. Read synchronization keeps raw source
identity and Relations; legacy task writes continue to use the configured task DB.
"""
from __future__ import annotations

from typing import Any, Callable

import httpx

from . import config

_BASE = "https://api.notion.com/v1"
_NOTION_VERSION = "2022-06-28"


class NotionError(RuntimeError):
    """Raised on connection, API, or source configuration errors."""


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
        raise NotionError(f"Notion API エラー {exc.response.status_code}: {exc.response.text[:300]}") from exc
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
        raise NotionError(f"Notion API エラー {exc.response.status_code}: {exc.response.text[:300]}") from exc
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
        raise NotionError(f"Notion API エラー {exc.response.status_code}: {exc.response.text[:300]}") from exc
    except httpx.HTTPError as exc:
        raise NotionError(f"Notion との通信に失敗しました: {exc}") from exc


# ---------------------------------------------------------------------------
# Property extraction helpers
# ---------------------------------------------------------------------------


def _extract_text(prop: dict[str, Any] | None) -> str:
    if not prop:
        return ""
    for kind in ("title", "rich_text"):
        items = prop.get(kind) or []
        if items:
            return "".join(str(item.get("plain_text") or "") for item in items)
    return ""


def _extract_select(prop: dict[str, Any] | None) -> str:
    if not prop:
        return ""
    for kind in ("select", "status"):
        value = prop.get(kind)
        if isinstance(value, dict):
            return str(value.get("name") or "")
    return ""


def _extract_date_range(prop: dict[str, Any] | None) -> tuple[str | None, str | None]:
    if not prop:
        return None, None
    value = prop.get("date")
    if not isinstance(value, dict):
        return None, None
    return value.get("start"), value.get("end")


def _extract_date(prop: dict[str, Any] | None) -> str | None:
    return _extract_date_range(prop)[0]


def _extract_multi_select(prop: dict[str, Any] | None) -> list[str]:
    if not prop:
        return []
    return [str(item.get("name")) for item in prop.get("multi_select") or [] if item.get("name")]


def _extract_relation_ids(prop: dict[str, Any] | None) -> list[str]:
    if not prop:
        return []
    result: list[str] = []
    for item in prop.get("relation") or []:
        value = str(item.get("id") or "").strip()
        if value and value not in result:
            result.append(value)
    return result


def _extract_people_ids(prop: dict[str, Any] | None) -> list[str]:
    if not prop:
        return []
    result: list[str] = []
    for item in prop.get("people") or []:
        value = str(item.get("id") or "").strip()
        if value and value not in result:
            result.append(value)
    return result


def _page_meta(page: dict[str, Any]) -> dict[str, Any]:
    return {
        "external_id": str(page.get("id") or ""),
        "url": str(page.get("url") or ""),
        "source_created_at": page.get("created_time"),
        "source_updated_at": page.get("last_edited_time"),
        "archived": bool(page.get("archived") or page.get("in_trash")),
    }


def parse_project_page(page: dict[str, Any]) -> dict[str, Any]:
    """Convert one project database page while preserving source Relations."""
    props = page.get("properties") or {}
    period_start, period_end = _extract_date_range(props.get(config.NOTION_PROJECT_PROP_PERIOD))
    return _page_meta(page) | {
        "title": _extract_text(props.get(config.NOTION_PROJECT_PROP_TITLE)),
        "status": _extract_select(props.get(config.NOTION_PROJECT_PROP_STATUS)) or "unknown",
        "owner_external_ids": _extract_people_ids(props.get(config.NOTION_PROJECT_PROP_OWNER)),
        "priority": _extract_select(props.get(config.NOTION_PROJECT_PROP_PRIORITY)) or None,
        "period_start": period_start,
        "period_end": period_end,
        "summary": _extract_text(props.get(config.NOTION_PROJECT_PROP_SUMMARY)) or None,
        "task_external_ids": _extract_relation_ids(props.get(config.NOTION_PROJECT_PROP_TASKS)),
        "blocked_by_external_ids": _extract_relation_ids(props.get(config.NOTION_PROJECT_PROP_BLOCKED_BY)),
    }


def parse_task_page(page: dict[str, Any]) -> dict[str, Any]:
    """Convert one task page, preserving Project, assignee, and task hierarchy."""
    props = page.get("properties") or {}
    categories = _extract_multi_select(props.get(config.NOTION_PROP_CATEGORY))
    project_ids = _extract_relation_ids(props.get(config.NOTION_TASK_PROP_PROJECT))
    parent_ids = _extract_relation_ids(props.get(config.NOTION_TASK_PROP_PARENT))
    return _page_meta(page) | {
        "title": _extract_text(props.get(config.NOTION_PROP_TITLE)),
        "status": _extract_select(props.get(config.NOTION_PROP_STATUS)) or "unknown",
        "due_date": _extract_date(props.get(config.NOTION_PROP_DUE)),
        "priority": _extract_select(props.get(config.NOTION_PROP_PRIORITY)) or None,
        "category": ", ".join(categories) if categories else None,
        "reason": _extract_text(props.get(config.NOTION_PROP_REASON)) or None,
        "done_date": _extract_date(props.get(config.NOTION_PROP_DONE_DATE)),
        "summary": _extract_text(props.get(config.NOTION_TASK_PROP_SUMMARY)) or None,
        "project_external_ids": project_ids,
        "project_external_id": project_ids[0] if project_ids else None,
        "assignee_external_ids": _extract_people_ids(props.get(config.NOTION_TASK_PROP_ASSIGNEE)),
        "parent_external_ids": parent_ids,
        "parent_external_id": parent_ids[0] if parent_ids else None,
        "subtask_external_ids": _extract_relation_ids(props.get(config.NOTION_TASK_PROP_SUBTASKS)),
    }


# Backward-compatible internal name used by existing writes/tests.
def _parse_page(page: dict[str, Any]) -> dict[str, Any]:
    return parse_task_page(page)


# ---------------------------------------------------------------------------
# Property write helpers
# ---------------------------------------------------------------------------


def _title_prop(value: str) -> dict[str, Any]:
    return {"title": [{"text": {"content": value}}]}


def _rich_text_prop(value: str) -> dict[str, Any]:
    return {"rich_text": [{"text": {"content": value}}]} if value else {"rich_text": []}


def _date_prop(value: str | None) -> dict[str, Any]:
    return {"date": {"start": value}} if value else {"date": None}


def _select_prop(value: str | None) -> dict[str, Any]:
    return {"select": {"name": value}} if value else {"select": None}


def _status_prop(value: str | None) -> dict[str, Any]:
    return {"status": {"name": value}} if value else {"status": None}


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
        props[config.NOTION_PROP_DONE_DATE] = _date_prop(done_date)
    return props


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def query_database_raw(
    db_id: str,
    filter_payload: dict[str, Any] | None = None,
    sorts: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Fetch all raw pages from one configured Notion database."""
    db_id = str(db_id or "").strip()
    if not db_id:
        raise NotionError("Notion database ID が設定されていません。")
    body: dict[str, Any] = {"page_size": 100}
    if filter_payload:
        body["filter"] = filter_payload
    if sorts:
        body["sorts"] = sorts
    pages: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        request = dict(body)
        if cursor:
            request["start_cursor"] = cursor
        data = _post(f"/databases/{db_id}/query", request)
        pages.extend(item for item in data.get("results") or [] if isinstance(item, dict))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
        if not cursor:
            break
    return pages


def _query_parsed(
    db_id: str,
    parser: Callable[[dict[str, Any]], dict[str, Any]],
    filter_payload: dict[str, Any] | None = None,
    sorts: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for page in query_database_raw(db_id, filter_payload, sorts):
        parsed = parser(page)
        if parsed.get("title") and not parsed.get("archived"):
            results.append(parsed)
    return results


def query_projects_database(
    db_id: str | None = None,
    filter_payload: dict[str, Any] | None = None,
    sorts: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    return _query_parsed(db_id or config.NOTION_PROJECTS_DB_ID, parse_project_page, filter_payload, sorts)


def query_tasks_database_v2(
    db_id: str | None = None,
    filter_payload: dict[str, Any] | None = None,
    sorts: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    return _query_parsed(db_id or config.NOTION_TASKS_DB_ID, parse_task_page, filter_payload, sorts)


def query_database(
    db_id: str | None = None,
    filter_payload: dict[str, Any] | None = None,
    sorts: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Backward-compatible task query, now returning Relation-aware fields too."""
    return query_tasks_database_v2(db_id, filter_payload, sorts)


def create_task_page(
    title: str,
    due_date: str | None = None,
    priority: str | None = None,
    categories: list[str] | None = None,
    reason: str | None = None,
    status: str | None = None,
    db_id: str | None = None,
) -> dict[str, Any]:
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
    return parse_task_page(_post("/pages", body, timeout=20))


def update_task_page(
    page_id: str,
    status: str | None = None,
    due_date: str | None = None,
    priority: str | None = None,
    categories: list[str] | None = None,
    reason: str | None = None,
    done_date: str | None = None,
) -> dict[str, Any]:
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
    return parse_task_page(_patch(f"/pages/{page_id}", {"properties": props}, timeout=20))
