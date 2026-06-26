"""Autonomous background scheduler for PETIT.

会話を N 時間おきに自動でまとめて蓄積する「自律性」の中核。
依存を増やさないため標準ライブラリの threading だけで実装する。

- daemon スレッドで Event.wait(interval) を回す（sleep より停止が速い）。
- 1日の最初のティックは kind="daily"、それ以外は "interval" として要約する。
- LM Studio が落ちていても summarizer 側が握りつぶすのでループは死なない。
"""
from __future__ import annotations

import logging
import threading
from datetime import date

from . import config, summarizer

log = logging.getLogger(__name__)


class SummaryScheduler:
    def __init__(self, interval_hours: float | None = None) -> None:
        self.interval_hours = interval_hours if interval_hours is not None else config.SUMMARY_INTERVAL_HOURS
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_day: date | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, name="petit-summarizer", daemon=True)
        self._thread.start()
        log.info("Summary scheduler started (interval=%.1fh)", self.interval_hours)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _next_kind(self) -> str:
        today = date.today()
        kind = "daily" if self._last_day is not None and today != self._last_day else "interval"
        self._last_day = today
        return kind

    def run_once(self) -> dict:
        """Run a single summarization pass now (used by the scheduler and /api/summarize)."""
        kind = self._next_kind()
        try:
            return summarizer.summarize_pending(kind=kind)
        except Exception as exc:  # noqa: BLE001 - a bad tick must not kill the loop
            log.warning("Summarization tick failed: %s", exc)
            return {"summarized": False, "reason": "exception", "error": str(exc)}

    def _run_loop(self) -> None:
        interval_seconds = max(60.0, self.interval_hours * 3600.0)
        # 起動直後は要約しない（最初の interval を待ってから）
        while not self._stop.wait(interval_seconds):
            result = self.run_once()
            if result.get("summarized"):
                log.info("Auto-summary: %s", result)


# Module-level singleton, started from main.py on app startup.
_scheduler: SummaryScheduler | None = None


def get_scheduler() -> SummaryScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = SummaryScheduler()
    return _scheduler
