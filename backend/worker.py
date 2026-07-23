"""Background job worker for PETIT."""
from __future__ import annotations

import json
import logging
import threading
from typing import Any

from . import config, daily_index, db, github_daily_review, notion_task_sync, task_sync_queue, web_sources

log = logging.getLogger(__name__)


class JobWorker:
    def __init__(self, interval_seconds: float = 2.0) -> None:
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        # Agent is fully imported by startup time, so Phase 2 routes can be
        # installed without participating in the agent -> tools import cycle.
        from .tools import tasks_phase2

        tasks_phase2.install_agent_routes()
        task_sync_queue.ensure_task_sync_schema()
        notion_task_sync.ensure_schema()
        notion_task_sync.request_startup_sync()
        github_daily_review.ensure_schema()
        daily_index.ensure_schema()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="petit-job-worker", daemon=True)
        self._thread.start()
        github_daily_review.get_scheduler().start()
        if config.DAILY_INDEX_ENABLED:
            daily_index.get_scheduler().start()

    def stop(self) -> None:
        self._stop.set()
        github_daily_review.get_scheduler().stop()
        if config.DAILY_INDEX_ENABLED:
            daily_index.get_scheduler().stop()
        if self._thread:
            self._thread.join(timeout=3)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job = db.claim_next_job()
                if job is not None:
                    _process_job(job)
                    continue
                # Outbound writes remain highest priority so PETIT changes reach
                # Notion quickly. Webhook inbox and repair pulls run afterwards.
                if task_sync_queue.process_next():
                    continue
                if notion_task_sync.process_inbox_next():
                    continue
                if notion_task_sync.run_due_sync():
                    continue
                self._stop.wait(self.interval_seconds)
            except Exception as exc:  # noqa: BLE001
                log.exception("Job worker loop failed: %s", exc)
                self._stop.wait(self.interval_seconds)


_worker = JobWorker()


def get_worker() -> JobWorker:
    return _worker


def _process_job(job: dict[str, Any]) -> None:
    job_id = int(job["id"])
    try:
        payload = json.loads(job.get("input_json") or "{}")
        if job["type"] == "background_research":
            result = _run_background_research(payload)
        elif job["type"] == "agent_followup":
            result = _run_agent_followup(payload)
        else:
            raise ValueError(f"unknown job type: {job['type']}")
        db.finish_job(job_id, result)
    except Exception as exc:  # noqa: BLE001
        db.fail_job(job_id, str(exc))


def _run_background_research(payload: dict[str, Any]) -> str:
    kind = (payload.get("kind") or "news").strip().lower()
    if kind == "weather":
        location = payload.get("location") or payload.get("query")
        result = web_sources.get_weather(str(location or ""), payload.get("date"))
        return web_sources.format_weather(result)

    query = payload.get("query") or payload.get("location") or "最新ニュース"
    result = web_sources.search_news(str(query), int(payload.get("limit") or 5))
    return web_sources.format_news(result)


def _run_agent_followup(payload: dict[str, Any]) -> str:
    message = str(payload.get("message") or "").strip()
    history = payload.get("history") or []
    if not message:
        raise ValueError("agent_followup requires message")

    from . import agent, chroma_client, markdown_export

    result = agent.run(message, history=history, allow_defer=False)
    used_tools_str = ", ".join(t["name"] for t in result["used_tools"]) or None
    reply = result["reply"]
    if not reply.strip():
        return ""
    conv_id = db.save_conversation(
        user_text=f"[follow-up] {message}",
        assistant_text=reply,
        used_tools=used_tools_str,
    )
    chroma_client.add(
        "petit_conversations",
        doc_id=f"conv_{conv_id}",
        text=f"ユーザー: {message}\nPETIT追加: {reply}",
        metadata={"timestamp": db.now_iso(), "kind": "agent_followup"},
    )
    markdown_export.append_conversation_turn(
        user_text=f"[follow-up] {message}",
        assistant_text=reply,
        used_tools=used_tools_str,
        timestamp=db.now_iso(),
    )
    return reply
