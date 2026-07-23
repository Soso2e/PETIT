"""Outbox/Inbox worker orchestration and repair synchronization."""
from __future__ import annotations

import logging
import threading
from datetime import timedelta
from typing import Any

from .. import config, db, notion_client, notion_project_sync, task_sync_queue
from . import merge, store

log = logging.getLogger(__name__)

_SYNC_LOCK = threading.Lock()
_STARTUP_SYNC_REQUESTED = False
_OUTBOX_APPLY_ORIGINAL: Any | None = None


def _apply_outbox_with_snapshot(operation: dict[str, Any], remote: dict[str, Any]) -> None:
    if _OUTBOX_APPLY_ORIGINAL is None:
        raise RuntimeError("task outbox snapshot hook is not initialized")
    _OUTBOX_APPLY_ORIGINAL(operation, remote)
    merge.save_snapshot(remote)


_apply_outbox_with_snapshot._petit_live_sync_wrapper = True  # type: ignore[attr-defined]


def _upsert_live(tasks: list[dict[str, Any]]) -> int:
    seen: set[str] = set()
    for task in tasks:
        external_id = str(task.get("external_id") or "").strip()
        if external_id:
            seen.add(external_id)
        merge.merge_remote_task(task)
    merge.mark_missing_after_full(seen, db.now_iso())
    return len(seen)


def install_sync_hooks() -> None:
    """Route legacy full reads and outbound acknowledgements through live snapshots."""
    global _OUTBOX_APPLY_ORIGINAL
    current_apply = task_sync_queue._apply_remote_result  # noqa: SLF001
    if not getattr(current_apply, "_petit_live_sync_wrapper", False):
        _OUTBOX_APPLY_ORIGINAL = current_apply
        task_sync_queue._apply_remote_result = _apply_outbox_with_snapshot  # type: ignore[assignment]  # noqa: SLF001
    # tasks_phase2 may install its old guard after this package was imported.
    notion_project_sync.upsert_tasks = _upsert_live


def ensure_schema() -> None:
    store.ensure_schema()
    install_sync_hooks()


def request_startup_sync() -> None:
    global _STARTUP_SYNC_REQUESTED
    _STARTUP_SYNC_REQUESTED = True


def _record_started() -> str:
    ensure_schema()
    now = db.now_iso()
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE notion_task_sync_state SET last_started_at=?, last_error=NULL WHERE provider=?",
            (now, store.SYNC_SOURCE),
        )
    return now


def _record_success(count: int, *, full: bool, cursor_at: str) -> dict[str, Any]:
    now = db.now_iso()
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE notion_task_sync_state SET last_success_at=?, last_failure_at=NULL, last_error=NULL, "
            "last_full_sync_at=CASE WHEN ? THEN ? ELSE last_full_sync_at END, pull_cursor_at=?, "
            "full_sync_requested=0, synced_count=? WHERE provider=?",
            (now, int(full), now, cursor_at, int(count), store.SYNC_SOURCE),
        )
    db.record_sync_success(store.SYNC_SOURCE, int(count))
    return {"ok": True, "finished_at": now, "synced_count": int(count), "mode": "full" if full else "incremental"}


def _record_failure(exc: Exception, *, mode: str) -> dict[str, Any]:
    error = str(exc)[:500] or type(exc).__name__
    now = db.now_iso()
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE notion_task_sync_state SET last_failure_at=?, last_error=? WHERE provider=?",
            (now, error, store.SYNC_SOURCE),
        )
    db.record_sync_failure(store.SYNC_SOURCE, error)
    return {"ok": False, "mode": mode, "error": error, "failed_at": now}


def _incremental_filter(cursor_at: str | None) -> dict[str, Any] | None:
    cursor = store.parse_time(cursor_at)
    if cursor is None:
        return None
    overlap = max(0.0, float(config.NOTION_TASK_SYNC_OVERLAP_SECONDS))
    since = (cursor - timedelta(seconds=overlap)).isoformat(timespec="seconds")
    return {"timestamp": "last_edited_time", "last_edited_time": {"on_or_after": since}}


def sync_now(mode: str = "incremental") -> dict[str, Any]:
    """Run a pull sync. Chat never calls this implicitly."""
    normalized = "full" if str(mode).strip().casefold() == "full" else "incremental"
    if not config.notion_configured():
        return {"ok": False, "skipped": True, "reason": "notion_not_configured", "mode": normalized}
    if not _SYNC_LOCK.acquire(blocking=False):
        return {"ok": True, "skipped": True, "reason": "already_running", "mode": normalized}
    started_at = _record_started()
    try:
        current = store.state()
        filter_payload = None if normalized == "full" else _incremental_filter(current.get("pull_cursor_at"))
        tasks = notion_client.query_tasks_database_v2(
            filter_payload=filter_payload,
            sorts=[{"timestamp": "last_edited_time", "direction": "ascending"}],
        )
        counts: dict[str, int] = {}
        seen: set[str] = set()
        for task in tasks:
            external_id = str(task.get("external_id") or "").strip()
            if external_id:
                seen.add(external_id)
            outcome = merge.merge_remote_task(task)
            counts[outcome] = counts.get(outcome, 0) + 1
        if normalized == "full":
            counts["deleted_missing"] = merge.mark_missing_after_full(seen, db.now_iso())
        result = _record_success(len(tasks), full=normalized == "full", cursor_at=started_at)
        result["counts"] = counts
        return result
    except Exception as exc:  # noqa: BLE001
        log.exception("Notion task %s sync failed", normalized)
        return _record_failure(exc, mode=normalized)
    finally:
        _SYNC_LOCK.release()


def request_full_sync() -> None:
    ensure_schema()
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE notion_task_sync_state SET full_sync_requested=1 WHERE provider=?",
            (store.SYNC_SOURCE,),
        )


def _belongs_to_task_database(task: dict[str, Any]) -> bool:
    parent_id = store.normalize_id(task.get("parent_database_id"))
    return bool(parent_id and parent_id in store.task_source_ids())


def process_inbox_next() -> bool:
    event = store.claim_inbox()
    if event is None:
        return False
    try:
        event_type = str(event["event_type"])
        entity_id = str(event.get("entity_id") or "")
        entity_type = str(event.get("entity_type") or "")
        if event_type in store.FULL_SYNC_EVENTS:
            if entity_id and store.normalize_id(entity_id) in store.task_source_ids():
                request_full_sync()
            store.finish_inbox(str(event["event_id"]), "done")
            return True
        if event_type not in store.PAGE_EVENTS or entity_type != "page" or not entity_id:
            store.finish_inbox(str(event["event_id"]), "done")
            return True
        if event_type == "page.deleted":
            merge.mark_remote_deleted(entity_id, event.get("event_timestamp"))
            store.finish_inbox(str(event["event_id"]), "done")
            return True
        raw_page = notion_client._get(f"/pages/{entity_id}", timeout=20)  # noqa: SLF001
        remote = notion_client.parse_task_page(raw_page)
        parent = raw_page.get("parent") if isinstance(raw_page.get("parent"), dict) else {}
        remote["parent_database_id"] = parent.get("database_id") or parent.get("data_source_id")
        if _belongs_to_task_database(remote):
            merge.merge_remote_task(remote)
        store.finish_inbox(str(event["event_id"]), "done")
    except Exception as exc:  # noqa: BLE001
        log.exception("Notion task webhook event failed: %s", event.get("event_id"))
        store.finish_inbox(str(event["event_id"]), "failed", error=str(exc))
    return True


def run_due_sync() -> bool:
    global _STARTUP_SYNC_REQUESTED
    ensure_schema()
    if not config.NOTION_TASK_BACKGROUND_SYNC_ENABLED or not config.notion_configured():
        return False
    current = store.state()
    if _STARTUP_SYNC_REQUESTED and config.NOTION_TASK_SYNC_ON_STARTUP:
        _STARTUP_SYNC_REQUESTED = False
        sync_now("full" if not current.get("last_full_sync_at") else "incremental")
        return True
    _STARTUP_SYNC_REQUESTED = False
    if int(current.get("full_sync_requested") or 0):
        sync_now("full")
        return True
    if store.due(current.get("last_full_sync_at"), config.NOTION_TASK_FULL_SYNC_INTERVAL_SECONDS):
        sync_now("full")
        return True
    if store.due(current.get("last_success_at"), config.NOTION_TASK_PULL_INTERVAL_SECONDS):
        sync_now("incremental")
        return True
    return False


def status() -> dict[str, Any]:
    ensure_schema()
    current = store.state()
    with db.get_connection() as conn:
        inbox_counts = {
            str(row["status"]): int(row["count"])
            for row in conn.execute("SELECT status, COUNT(*) AS count FROM notion_task_inbox GROUP BY status").fetchall()
        }
        task_counts = {
            str(row["sync_status"]): int(row["count"])
            for row in conn.execute("SELECT sync_status, COUNT(*) AS count FROM tasks_cache GROUP BY sync_status").fetchall()
        }
        active_remote = int(conn.execute(
            "SELECT COUNT(*) FROM tasks_cache WHERE source='notion' AND remote_deleted_at IS NULL"
        ).fetchone()[0])
    current.pop("webhook_verification_token", None)
    stale = bool(config.notion_configured() and store.due(
        current.get("last_success_at"), config.NOTION_TASK_PULL_INTERVAL_SECONDS * 2
    ))
    return {
        "configured": config.notion_configured(),
        "mode": "local_first_outbox_inbox",
        "background_enabled": config.NOTION_TASK_BACKGROUND_SYNC_ENABLED,
        "stale": stale,
        "pull_interval_seconds": config.NOTION_TASK_PULL_INTERVAL_SECONDS,
        "full_sync_interval_seconds": config.NOTION_TASK_FULL_SYNC_INTERVAL_SECONDS,
        "webhook": {
            "signature_required": config.NOTION_WEBHOOK_REQUIRE_SIGNATURE,
            "verification_token_stored": bool(store.stored_verification_token()),
            "last_received_at": current.get("last_webhook_at"),
            "last_event_id": current.get("last_event_id"),
            "inbox_counts": inbox_counts,
        },
        "pull": {
            "last_started_at": current.get("last_started_at"),
            "last_success_at": current.get("last_success_at"),
            "last_failure_at": current.get("last_failure_at"),
            "last_error": current.get("last_error"),
            "last_full_sync_at": current.get("last_full_sync_at"),
            "cursor_at": current.get("pull_cursor_at"),
            "full_sync_requested": bool(current.get("full_sync_requested")),
            "synced_count": int(current.get("synced_count") or 0),
        },
        "tasks": {
            "active_remote": active_remote,
            "sync_status_counts": task_counts,
            "pending_writes": int(task_counts.get("pending", 0)),
            "failed_writes": int(task_counts.get("failed", 0)),
            "conflicts": int(task_counts.get("conflict", 0)),
        },
    }
