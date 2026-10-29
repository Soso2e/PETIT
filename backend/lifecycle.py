"""Application startup and shutdown lifecycle wiring."""
from __future__ import annotations

import logging
import threading

from fastapi import FastAPI

from . import chroma_client, config, db, notifications, scheduler, vault_indexer, worker

log = logging.getLogger(__name__)


def register(app: FastAPI) -> None:
    """Register PETIT startup and shutdown handlers on the FastAPI app."""
    app.router.add_event_handler("startup", startup)
    app.router.add_event_handler("shutdown", shutdown)


def startup() -> None:
    from . import setup_store, service_sync
    setup_store.apply_runtime()
    db.init_db()
    from . import conversation_store
    conversation_store.recover()
    from . import attachments
    attachments.start_cleanup()
    notifications.init_db()
    # Sync existing SQLite data into Chroma in background (best-effort)
    threading.Thread(target=_chroma_sync, daemon=True).start()
    # Autonomous summarizer: fold conversations into memory every N hours
    if config.AUTO_SUMMARY_ENABLED:
        scheduler.get_scheduler().start()
    worker.get_worker().start()
    # Complete this shared lazy migration before first-run UI requests race each other.
    from . import task_hierarchy
    task_hierarchy.ensure_task_hierarchy_schema()
    service_sync.start()


def shutdown() -> None:
    from . import service_sync, codex_brain
    service_sync.stop()
    codex_brain.shutdown()
    from . import attachments
    attachments.stop_cleanup()
    if config.AUTO_SUMMARY_ENABLED:
        scheduler.get_scheduler().stop()
    worker.get_worker().stop()


def _chroma_sync() -> None:
    """Incrementally index SQLite memory/episodes and configured vaults."""
    try:
        mem_rows = db.all_memory()
        counts = chroma_client.sync_structured_data(mem_rows, db.all_episodes())
        vault_counts = vault_indexer.index_configured_vaults()
        if any(counts.values()) or vault_counts.get("chunks"):
            log.info("Chroma sync: %s vault=%s", counts, vault_counts)
    except Exception as exc:  # noqa: BLE001
        log.debug("Chroma startup sync skipped: %s", exc)
