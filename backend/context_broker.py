"""Read-only context aggregation for the PETIT Brain."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timedelta
from threading import BoundedSemaphore
from typing import Any
from zoneinfo import ZoneInfo

from . import config, db, tools

SUPPORTED_SOURCES = ("tasks", "calendar", "memory", "brain", "work", "reminders", "handoff")
_SUPPORTED_SOURCES = set(SUPPORTED_SOURCES)
_TZ = ZoneInfo("Asia/Tokyo")
_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="petit-context")
_SLOTS = BoundedSemaphore(4)


def normalize_request(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    needs: list[dict[str, Any]] = []
    items = raw.get("needs")
    for item in (items[:12] if isinstance(items, list) else []):
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "").strip().lower()
        if source not in _SUPPORTED_SOURCES:
            continue
        normalized = {"source": source}
        for key in ("scope", "priority", "date", "query"):
            candidate = str(item.get(key) or "").strip()
            if candidate:
                normalized[key] = candidate[:500]
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
        name, arguments = "get_tasks", {"limit": 40}
    elif source == "calendar":
        name, arguments = "get_schedule", {"date": _resolve_date(need)}
    elif source in {"memory", "brain"}:
        query = need.get("query", "").strip()
        if not query:
            return {"error": "query_required"}
        name = "search_memory" if source == "memory" else "search_brain_notes"
        arguments = {"query": query, "limit": 5}
        if source == "memory":
            arguments["include_vault"] = False
    elif source == "work":
        name, arguments = "get_work_status", {}
    elif source == "reminders":
        name, arguments = "get_reminders", {"scope": "upcoming", "limit": 20}
    elif source == "handoff":
        # restore_context's latest handoff is global; filter before choosing one.
        query = need.get("query", "").strip()
        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT id, created_at, current_project, stopped_at, next_action, blockers "
                "FROM handoff_notes WHERE ? = '' OR instr(lower(COALESCE(current_project, '')), lower(?)) > 0 "
                "ORDER BY id DESC LIMIT 5", (query, query),
            ).fetchall()
        return {"handoffs": [dict(row) for row in rows]}
    else:
        return {"error": "unsupported_source", "source": source}
    if tools.risk_for(name) != "safe_read":
        return {"error": "read_boundary_violation"}
    raw = tools.dispatch(name, arguments)
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"error": "invalid_tool_result", "source": source}
    return parsed if isinstance(parsed, dict) else {"error": "invalid_tool_result"}


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
    sync = None
    if not isinstance(result, dict):
        raise ValueError("invalid_tool_result")
    expected = {"tasks": "tasks", "calendar": "events", "memory": "memories", "brain": "vault_notes",
                "work": "tasks", "reminders": "items", "handoff": "handoffs"}[source]
    if not result.get("error"):
        if expected not in result:
            raise ValueError("invalid_tool_result")
        _rows(result, expected)
    if source == "tasks":
        facts = _task_facts(result, need)
        sync = result.get("sync")
    elif source == "calendar":
        facts = _calendar_facts(result)
        sync = result.get("calendar_sync")
    else:
        facts = _personal_facts(source, result)
    sync = sync if isinstance(sync, dict) else {}
    error = result.get("error")
    incomplete = bool(error or result.get("errors") or result.get("ok") is False
                      or sync.get("error") or sync.get("errors") or sync.get("ok") is False
                      or sync.get("status") in {"failed", "error", "unavailable"})
    stale = bool(result.get("stale") or sync.get("stale"))
    for provider in sync.get("sources", []) if isinstance(sync.get("sources"), list) else []:
        if isinstance(provider, dict):
            incomplete |= bool(provider.get("error") or provider.get("ok") is False)
            stale |= bool(provider.get("stale"))
    known_error = error if error in {"query_required", "invalid_tool_result", "timeout", "source_busy", "read_boundary_violation"} else None
    freshness = {key: sync[key] for key in ("last_synced_at", "last_success_at", "cached")
                 if isinstance(sync.get(key), (str, bool))}
    freshness["status"] = "historical" if source in {"memory", "brain", "handoff"} else (
        "local" if source in {"work", "reminders"} else str(sync.get("status") or "unknown")[:40])
    compact, truncated = _bounded_facts([] if error else facts)
    limits = {"tasks": {"tasks": 20}, "calendar": {"events": 20},
              "memory": {"memories": 5, "episodes": 5}, "brain": {"vault_notes": 5},
              "work": {"tasks": 5}, "reminders": {"items": 5}, "handoff": {"handoffs": 5}}
    truncated |= any(isinstance(result.get(key), list) and len(result[key]) > limit
                     for key, limit in limits[source].items())
    return {
        "source": source,
        "need": need,
        "facts": compact,
        "count": len(compact),
        "truncated": truncated,
        "collected_at": datetime.now(_TZ).isoformat(timespec="seconds"),
        "freshness": freshness,
        "stale": stale,
        "error": known_error or ("source_incomplete" if incomplete else None),
    }


def _rows(result: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = result.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError("invalid_tool_result")
    return value


def _personal_facts(source: str, result: dict[str, Any]) -> list[dict[str, Any]]:
    fields = {
        "memories": ("content", "type", "created_at", "relevance"),
        "episodes": ("title", "text", "summary", "started_at", "relevance"),
        "vault_notes": ("relative_path", "heading", "text", "modified_at"),
        "reminders": ("id", "title", "trigger_at", "status", "related_task_id"),
        "handoffs": ("id", "created_at", "current_project", "stopped_at", "next_action", "blockers"),
    }
    if source == "work":
        facts = [{"kind": "today_total", "date": result.get("date"), "total_seconds": result.get("total_seconds")}]
        active = result.get("active")
        if isinstance(active, dict):
            facts.append({"kind": "active", **{key: active.get(key) for key in
                         ("task", "task_id", "project_id", "status", "elapsed_seconds")}})
        facts.extend({"kind": "task_total", **{key: task.get(key) for key in
                      ("task", "task_id", "project_id", "elapsed_seconds")}}
                     for task in _rows(result, "tasks")[:5])
        return facts
    groups = {"memory": ("memories", "episodes"), "brain": ("vault_notes",),
              "reminders": ("reminders",), "handoff": ("handoffs",)}[source]
    facts = []
    for group in groups:
        for item in _rows(result, "items" if group == "reminders" else group)[:5]:
            facts.append({"kind": group, **{key: item.get(key) for key in fields[group]}})
    return facts


def _bounded_facts(facts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    compact = []
    size = 0
    truncated = False
    for fact in facts:
        row = {key: value[:360] if isinstance(value, str) else value
               for key, value in fact.items() if value is None or isinstance(value, (str, int, float, bool))}
        truncated |= row != fact
        size += len(json.dumps(row, ensure_ascii=False))
        if size > 2500:
            return compact, True
        compact.append(row)
    return compact, truncated


def collect(request: dict[str, Any]) -> dict[str, Any]:
    """Collect independent read sources in parallel and return compact AI-facing facts."""
    normalized = normalize_request(request)
    needs = normalized["needs"]
    if not needs:
        return {"goal": normalized["goal"], "sources": [], "partial": True, "errors": ["no_supported_needs"]}

    sources: list[dict[str, Any]] = []
    errors: list[str] = []
    future_map = {}
    results = []
    for need in needs:
        if not _SLOTS.acquire(blocking=False):
            results.append((need, {"error": "source_busy"}))
            continue
        try:
            future = _POOL.submit(_dispatch, need["source"], need)
        except Exception:
            _SLOTS.release()
            results.append((need, {"error": "source_busy"}))
            continue
        future.add_done_callback(lambda _: _SLOTS.release())
        future_map[future] = need
    _, pending = wait(future_map, timeout=config.CONTEXT_BROKER_TIMEOUT_SECONDS)
    for future, need in future_map.items():
        if future in pending:
            future.cancel()
            result = {"error": "timeout"}
        else:
            try:
                result = future.result()
            except Exception:  # provider errors may contain credentials or private URLs
                result = {"error": "provider_failed"}
        results.append((need, result))
    for need, result in results:
        source = need["source"]
        try:
            packet = _normalize_source(source, need, result)
        except (TypeError, ValueError, AttributeError):
            packet = _normalize_source(source, need, {"error": "invalid_tool_result"})
        if packet.get("error") or packet.get("stale"):
            errors.append(f"{source}: {packet.get('error') or 'stale'}")
        sources.append(packet)

    sources.sort(key=lambda item: SUPPORTED_SOURCES.index(item["source"]))
    return {
        "goal": normalized["goal"],
        "sources": sources,
        "partial": bool(errors),
        "errors": errors,
    }


def render_for_model(packet: dict[str, Any]) -> str:
    return json.dumps(packet, ensure_ascii=False, default=str, separators=(",", ":"))
