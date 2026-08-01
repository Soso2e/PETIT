from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from backend import config, work_sessions


class WorkSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "petit.db"
        self.db_patch = patch.object(config, "DB_PATH", self.db_path)
        self.db_patch.start()
        work_sessions.ensure_schema()
        self.now = datetime(2026, 8, 1, 3, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_check_in_then_auto_stop_without_response(self) -> None:
        work_sessions.start_session("session-1", "テスト作業", now=self.now)
        sent: list[dict] = []

        first = work_sessions.run_due_checks(
            now=self.now + timedelta(minutes=20),
            dispatch=lambda **values: sent.append(values) or {"sent": 0},
        )
        self.assertEqual(first, {"checked": 1, "auto_stopped": 0})
        self.assertIn("返事がなければ20分後", sent[0]["body"])
        self.assertIsNotNone(work_sessions._row("session-1")["awaiting_response_since"])

        second = work_sessions.run_due_checks(
            now=self.now + timedelta(minutes=40),
            dispatch=lambda **values: sent.append(values) or {"sent": 0},
        )
        self.assertEqual(second, {"checked": 0, "auto_stopped": 1})
        self.assertEqual(work_sessions._row("session-1")["status"], "auto_stopped")
        self.assertIn("時間の加算を止めた", sent[1]["body"])

    def test_response_clears_timeout_and_schedules_next_check(self) -> None:
        work_sessions.start_session("session-2", "継続作業", now=self.now)
        work_sessions.run_due_checks(
            now=self.now + timedelta(minutes=20),
            dispatch=lambda **_values: {"sent": 0},
        )
        response_time = self.now + timedelta(minutes=25)
        session = work_sessions.respond("session-2", now=response_time)
        self.assertIsNotNone(session)
        self.assertIsNone(session["awaiting_response_since"])

        before_next = work_sessions.run_due_checks(
            now=response_time + timedelta(minutes=19),
            dispatch=lambda **_values: {"sent": 0},
        )
        self.assertEqual(before_next, {"checked": 0, "auto_stopped": 0})
        self.assertEqual(work_sessions._row("session-2")["status"], "active")

    def test_early_response_does_not_postpone_first_check(self) -> None:
        work_sessions.start_session("session-early", "先回り返答", now=self.now)
        self.assertIsNone(work_sessions.respond("session-early", now=self.now + timedelta(minutes=5)))
        due = work_sessions.run_due_checks(
            now=self.now + timedelta(minutes=20),
            dispatch=lambda **_values: {"sent": 0},
        )
        self.assertEqual(due, {"checked": 1, "auto_stopped": 0})

    def test_pause_does_not_accumulate_or_notify_until_resumed(self) -> None:
        work_sessions.start_session("session-3", "休憩する作業", now=self.now)
        work_sessions.pause_session("session-3", now=self.now + timedelta(minutes=5))
        due = work_sessions.run_due_checks(
            now=self.now + timedelta(hours=2),
            dispatch=lambda **_values: self.fail("paused session must not notify"),
        )
        self.assertEqual(due, {"checked": 0, "auto_stopped": 0})
        resumed = work_sessions.resume_session("session-3", now=self.now + timedelta(hours=2))
        self.assertEqual(resumed["status"], "active")
        self.assertEqual(resumed["paused_total_seconds"], 6900)


if __name__ == "__main__":
    unittest.main()
