from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from backend import config, work_sessions


class WorkSessionTodayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(config, "DB_PATH", Path(self.temp_dir.name) / "test.db")
        self.db_patch.start()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_today_summary_counts_active_session(self) -> None:
        start = datetime(2026, 8, 2, 0, 0, tzinfo=timezone.utc)
        work_sessions.start_session(
            "s1", "PETIT開発", task_id="notion-task-1", project_id="PETIT", now=start
        )
        summary = work_sessions.today_summary(now=start + timedelta(minutes=45))
        self.assertEqual(summary["total_seconds"], 45 * 60)
        self.assertEqual(summary["projects"][0]["project"], "PETIT")
        self.assertEqual(summary["tasks"], [{
            "task_id": "notion-task-1",
            "task": "PETIT開発",
            "project_id": "PETIT",
            "elapsed_seconds": 45 * 60,
        }])
        self.assertEqual(summary["active"]["session_id"], "s1")
        self.assertEqual(summary["active"]["elapsed_seconds"], 45 * 60)

    def test_today_summary_excludes_pause_time(self) -> None:
        start = datetime(2026, 8, 2, 1, 0, tzinfo=timezone.utc)
        work_sessions.start_session("s1", "Maya", project_id="Maya", now=start)
        work_sessions.pause_session("s1", now=start + timedelta(minutes=20))
        work_sessions.resume_session("s1", now=start + timedelta(minutes=50))
        work_sessions.end_session("s1", now=start + timedelta(minutes=80))
        summary = work_sessions.today_summary(now=start + timedelta(minutes=90))
        self.assertEqual(summary["total_seconds"], 50 * 60)

    def test_period_summary_groups_repeated_sessions_by_task(self) -> None:
        start = datetime(2026, 8, 1, 15, 0, tzinfo=timezone.utc)  # 2026-08-02 00:00 JST
        work_sessions.start_session("s1", "PETIT開発", task_id="task-1", project_id="PETIT", now=start)
        work_sessions.end_session("s1", now=start + timedelta(minutes=30))
        work_sessions.start_session(
            "s2", "PETIT開発", task_id="task-1", project_id="PETIT", now=start + timedelta(days=1)
        )
        work_sessions.end_session("s2", now=start + timedelta(days=1, minutes=45))

        summary = work_sessions.period_summary(days=2, now=start + timedelta(days=1, hours=1))

        self.assertEqual(summary["total_seconds"], 75 * 60)
        self.assertEqual([day["elapsed_seconds"] for day in summary["daily"]], [30 * 60, 45 * 60])
        self.assertEqual(summary["tasks"][0]["task_id"], "task-1")
        self.assertEqual(summary["tasks"][0]["elapsed_seconds"], 75 * 60)
        self.assertEqual(summary["tasks"][0]["session_count"], 2)

    def test_event_history_counts_pause_across_local_midnight(self) -> None:
        start = datetime(2026, 8, 1, 14, 30, tzinfo=timezone.utc)  # 23:30 JST
        work_sessions.start_session("s1", "深夜作業", now=start)
        work_sessions.pause_session("s1", now=start + timedelta(minutes=45))  # 00:15 JST
        work_sessions.resume_session("s1", now=start + timedelta(minutes=75))
        work_sessions.end_session("s1", now=start + timedelta(minutes=105))

        summary = work_sessions.period_summary(days=2, now=start + timedelta(hours=2))

        self.assertEqual([day["elapsed_seconds"] for day in summary["daily"]], [30 * 60, 45 * 60])


if __name__ == "__main__":
    unittest.main()
