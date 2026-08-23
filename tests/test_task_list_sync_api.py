from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from backend import task_list_api


class TaskListSyncApiTests(unittest.TestCase):
    def test_universe_tasks_view_exposes_refresh_and_recovery_actions(self) -> None:
        root = Path(__file__).resolve().parents[1]
        html = (root / "frontend" / "universe.html").read_text(encoding="utf-8")
        recovery_script = (root / "frontend" / "task-sync-recovery.js").read_text(encoding="utf-8")
        self.assertIn('id="refresh-tasks"', html)
        self.assertIn("/api/notifications/tasks/sync", recovery_script)
        self.assertIn("/sync/retry", recovery_script)
        self.assertIn("競合を確認して再編集", recovery_script)

    def test_explicit_ui_sync_uses_incremental_mode(self) -> None:
        with patch.object(task_list_api.notion_task_sync, "sync_now", return_value={"ok": True, "synced_count": 3}) as sync:
            response = task_list_api.sync_ui_tasks()
        self.assertEqual(response.status_code, 200)
        sync.assert_called_once_with(mode="incremental")

    def test_retry_endpoint_returns_conflict_as_client_error(self) -> None:
        with patch.object(task_list_api.task_sync_queue, "retry_task", return_value={"queued": False, "conflict": True}) as retry:
            response = task_list_api.retry_ui_task_sync(7)
        self.assertEqual(response.status_code, 409)
        retry.assert_called_once_with(7)


if __name__ == "__main__":
    unittest.main()
