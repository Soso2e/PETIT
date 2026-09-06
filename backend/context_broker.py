"""Read-only context aggregation for the PETIT Brain."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from . import tools

_SUPPORTED_SOURCES = {"tasks", "calendar"}
_TZ = ZoneInfo("Asia/Tokyo")


def normalize_request(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    needs: list[dict[str, Any]] = []
    for item in raw.get("needs") or []:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "").strip().lower()
        if source not in _SUPPORTED_SOURCES:
            continue
        normalized = {"source": source}
        for key in ("scope", "priority", "date"):
            candidate = str(item.get(key) or "").strip()
            if candidate:
                normalized[key] = candidate
        if normalized not in needs:
            needs.append(normalized)
    return {
        "needs": needs[:4],
        "goal": str(raw.get("goal") or "").strip()[:500],
    }


def _resolve_date(need: dict[str, Any]) -> str | None:
    explicit = str(need.get("date") or "").strip()
    if explicit:
        return explicit
    scope = str(need.get("scope") or "").strip().lower()
    today = datetime.now(_TZ).date()
    if scope in {"today", "今日"}:
        return today.isoformat()
    if scope in {"tomorrow", "明日"}:
        return (today + timedelta(days=1)).isoformat()
    return None


def _dispatch(source: str, need: dict[str, Any]) -> dict[str, Any]:
    if source == "tasks":
        raw = tools.dispatch("get_tasks", {"limit": 40})
    elif source == "calendar":
        raw = tools.dispatch("get_schedule", {"date": _resolve_date(need)})
    else:
        return {"error": "unsupported_source", "source": source}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"error": "invalid_tool_result", "source": source, "raw": str(raw)[:500]}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _task_facts(result: dict[str, Any], need: dict[str, Any]) -> list[dict[str, Any]]:
    priority = str(need.get("priority") or "").strip().casefold()
    facts: list[dict[str, Any]] = []
    for task in result.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        task_priority = str(task.get("priority") or "")
        if priority and priority != "all" and task_priority.casefold() != priority:
            continue
        facts.append(
            {
                "title": task.get("title"),
                "priority": task.get("priority"),
                "due_date": task.get("due_date"),
                "area": task.get("area"),
                "project_id": task.get("project_id"),
                "status": task.get("status"),
            }
        )
    return facts[:20]


def _calendar_facts(result: dict[str, Any]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for event in result.get("events") or []:
        if not isinstance(event, dict):
            continue
        facts.append(
            {
                "title": event.get("title"),
                "start_time": event.get("start_time"),
                "end_time": event.get("end_time"),
                "location": event.get("location"),
            }
        )
    return facts[:20]


def _normalize_source(source: str, need: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    if source == "tasks":
        facts = _task_facts(result, need)
        sync = result.get("sync")
    else:
        facts = _calendar_facts(result)
        sync = result.get("calendar_sync")
    error = result.get("error") if isinstance(result, dict) else None
    return {
        "source": source,
        "need": need,
        "facts": facts,
        "count": len(facts),
        "freshness": sync,
        "error": error,
    }


def collect(request: dict[str, Any]) -> dict[str, Any]:
    """Collect independent read sources in parallel and return compact AI-facing facts."""
    normalized = normalize_request(request)
    needs = normalized["needs"]
    if not needs:
        return {"goal": normalized["goal"], "sources": [], "partial": True, "errors": ["no_supported_needs"]}

    sources: list[dict[str, Any]] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=min(4, len(needs))) as executor:
        future_map = {
            executor.submit(_dispatch, need["source"], need): need
            for need in needs
        }
        for future in as_completed(future_map):
            need = future_map[future]
            source = need["source"]
            try:
                result = future.result()
            except Exception as exc:  # provider failure must not cancel other sources
                result = {"error": f"{type(exc).__name__}: {exc}"}
            packet = _normalize_source(source, need, result)
            if packet.get("error"):
                errors.append(f"{source}: {packet['error']}")
            sources.append(packet)

    sources.sort(key=lambda item: ("tasks", "calendar").index(item["source"]))
    return {
        "goal": normalized["goal"],
        "sources": sources,
        "partial": bool(errors),
        "errors": errors,
    }


def render_for_model(packet: dict[str, Any]) -> str:
    return json.dumps(packet, ensure_ascii=False, default=str, separators=(",", ":"))
