"""Background job worker for PETIT."""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from . import db, web_sources

log = logging.getLogger(__name__)


class JobWorker:
    def __init__(self, interval_seconds: float = 2.0) -> None:
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="petit-job-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job = db.claim_next_job()
                if job is None:
                    self._stop.wait(self.interval_seconds)
                    continue
                _process_job(job)
            except Exception as exc:  # noqa: BLE001
                log.exception("Job worker loop failed: %s", exc)
                self._stop.wait(self.interval_seconds)


_worker = JobWorker()


def get_worker() -> JobWorker:
    return _worker


def _process_job(job: dict[str, Any]) -> None:
    job_id = int(job["id"])
    try:
        if job["type"] != "background_research":
            raise ValueError(f"unknown job type: {job['type']}")
        payload = json.loads(job.get("input_json") or "{}")
        result = _run_background_research(payload)
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
