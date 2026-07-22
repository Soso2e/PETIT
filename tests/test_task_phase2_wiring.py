from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import agent, config, db, task_sync_queue, worker
from backend.tools import registry, task_defaults, task_reads, tasks_phase2


class TaskPhase2WiringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(config, "DB_PATH", Path(self.tmp.name) / "petit.sqlite3")
        self.db_patch.start()
        db.init_db()
        task_sync_queue.ensure_task_sync_schema()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.tmp.cleanup()

    def test_phase2_handlers_override_legacy_registry_entries(self) -> None:
        # Read behavior is tightened after Phase 2 registration. create_task adds
        # only conversation defaults and delegates the actual optimistic write and
        # queueing to Phase 2; the other write handlers remain directly owned there.
        self.assertIs(registry._REGISTRY["get_tasks"].handler, task_reads.get_tasks)
        self.assertIs(registry._REGISTRY["create_task"].handler, task_defaults.create_task)
        self.assertIs(registry._REGISTRY["complete_task"].handler, tasks_phase2.complete_task)
        self.assertIs(registry._REGISTRY["update_task"].handler, tasks_phase2.update_task)
        self.assertTrue(registry._REGISTRY["update_task"].requires_confirmation)
        self.assertTrue(registry._REGISTRY["retry_task_sync"].requires_confirmation)

    def test_agent_routes_are_installed_once(self) -> None:
        tasks_phase2.install_agent_routes()
        tasks_phase2.install_agent_routes()
        names = [name for name, _signals in agent._TOOL_SIGNALS]
        self.assertEqual(names.count("update_task"), 1)
        self.assertEqual(names.count("retry_task_sync"), 1)
        self.assertEqual(names.count("get_task_sync_status"), 1)
        self.assertIn("update_task", agent._related_tool_names("タスクの期限を変更して"))
        self.assertIn("retry_task_sync", agent._related_tool_names("タスク同期を再試行して"))

    def test_background_worker_processes_notion_task_queue(self) -> None:
        with patch.object(config, "notion_configured", return_value=True):
            created = tasks_phase2.create_task("Worker同期テスト")
        task_id = int(created["task"]["id"])
        remote = {
            "external_id": "remote-worker",
            "title": "Worker同期テスト",
            "status": config.NOTION_DEFAULT_STATUS,
            "due_date": None,
            "priority": "Mid",
            "category": None,
            "area": None,
            "reason": None,
            "url": "https://notion.so/remote-worker",
            "done_date": None,
            "project_external_ids": [],
            "assignee_external_ids": [],
            "parent_external_ids": [],
            "subtask_external_ids": [],
            "summary": None,
            "source_updated_at": "2026-07-21T12:00:00.000Z",
        }

        instance = worker.JobWorker(interval_seconds=0.01)
        with patch.object(task_sync_queue, "create_task_page", return_value=remote):
            instance.start()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                with db.get_connection() as conn:
                    row = conn.execute(
                        "SELECT sync_status, external_id FROM tasks_cache WHERE id=?",
                        (task_id,),
                    ).fetchone()
                if row and row["sync_status"] == "synced":
                    break
                time.sleep(0.02)
            instance.stop()

        self.assertIsNotNone(row)
        self.assertEqual(row["sync_status"], "synced")
        self.assertEqual(row["external_id"], "remote-worker")


if __name__ == "__main__":
    unittest.main()
