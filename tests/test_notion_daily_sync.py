"""Nightly Notion sync: pull-first, daily slot, never duplicate writes."""
from __future__ import annotations

import sqlite3
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from backend.notion_task_sync import runtime


class NotionDailySyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            "CREATE TABLE notion_task_sync_state "
            "(provider TEXT PRIMARY KEY, daily_slot TEXT, daily_status TEXT, "
            "daily_finished_at TEXT, daily_error TEXT)"
        )
        self.conn.execute(
            "INSERT INTO notion_task_sync_state(provider) VALUES (?)",
            (runtime.store.SYNC_SOURCE,),
        )
        self.conn.commit()
        self.addCleanup(self.conn.close)

    def state(self):
        return dict(self.conn.execute("SELECT * FROM notion_task_sync_state").fetchone())

    def test_slot_is_anchored_to_2am_jst(self):
        self.assertEqual(runtime.daily_slot(datetime(2026, 10, 23, 16, 59, tzinfo=timezone.utc)), "2026-10-23")
        self.assertEqual(runtime.daily_slot(datetime(2026, 10, 23, 17, 0, tzinfo=timezone.utc)), "2026-10-24")
        self.assertEqual(runtime.daily_slot(datetime(2026, 10, 24, 1, 0, tzinfo=timezone.utc)), "2026-10-24")

    def test_pull_then_push_then_verify_once_per_slot(self):
        steps = []

        def pull(mode):
            steps.append("pull_" + mode)
            return {"ok": True, "synced_count": 2}

        def push():
            steps.append("push")
            return len([s for s in steps if s == "push"]) == 1

        with patch.object(runtime.db, "get_connection", return_value=self.conn), \
             patch.object(runtime, "daily_slot", return_value="2026-10-24"), \
             patch.object(runtime, "sync_now", side_effect=pull), \
             patch.object(runtime.task_sync_queue, "process_next", side_effect=push), \
             patch.object(runtime.task_sync_queue, "status", return_value={"counts": {"synced": 2}}), \
             patch.object(runtime.config, "NOTION_TASK_DAILY_MAX_WRITES", 20), \
             patch.object(runtime.config, "NOTION_TASK_DAILY_WRITE_INTERVAL_SECONDS", 0):
            self.assertTrue(runtime.run_daily_if_due())
            self.assertFalse(runtime.run_daily_if_due())
        self.assertEqual(steps, ["pull_full", "push", "push", "pull_incremental"])
        self.assertEqual(self.state()["daily_status"], "success")

    def test_failed_pull_blocks_all_pushes(self):
        with patch.object(runtime.db, "get_connection", return_value=self.conn), \
             patch.object(runtime, "daily_slot", return_value="2026-10-24"), \
             patch.object(runtime, "sync_now", return_value={"ok": False, "error": "offline"}), \
             patch.object(runtime.task_sync_queue, "process_next") as push:
            self.assertTrue(runtime.run_daily_if_due())
            self.assertFalse(runtime.run_daily_if_due())
        push.assert_not_called()
        self.assertEqual(self.state()["daily_status"], "failed")
        self.assertIn("offline", self.state()["daily_error"])

    def test_conflict_makes_partial_not_success(self):
        with patch.object(runtime.db, "get_connection", return_value=self.conn), \
             patch.object(runtime, "daily_slot", return_value="2026-10-24"), \
             patch.object(runtime, "sync_now", return_value={"ok": True}), \
             patch.object(runtime.task_sync_queue, "process_next", return_value=False), \
             patch.object(runtime.task_sync_queue, "status", return_value={"counts": {"conflict": 1}}):
            self.assertTrue(runtime.run_daily_if_due())
        self.assertEqual(self.state()["daily_status"], "partial")

    def test_off_mode_never_runs_background_pull(self):
        with patch.object(runtime.config, "NOTION_TASK_SYNC_MODE", "off"), \
             patch.object(runtime.config, "NOTION_TASK_BACKGROUND_SYNC_ENABLED", True), \
             patch.object(runtime.config, "notion_configured", return_value=True), \
             patch.object(runtime, "sync_now") as pull:
            self.assertFalse(runtime.run_due_sync())
        pull.assert_not_called()


if __name__ == "__main__":
    unittest.main()
