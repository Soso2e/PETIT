from __future__ import annotations

import importlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import config, db, tools
from backend.tools import task_reads


class TaskConversationFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        # Other test modules can import the legacy task tool in the same process.
        # Re-run the status-aware decorator so this suite does not depend on import order.
        importlib.reload(task_reads)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(config, "DB_PATH", Path(self.temp_dir.name) / "app.db")
        self.db_patch.start()
        self.sync_patch = patch.object(
            task_reads.legacy_tasks,
            "_try_notion_sync",
            return_value={"configured": True, "fresh": True, "status": "success"},
        )
        self.sync_patch.start()
        db.init_db()

    def tearDown(self) -> None:
        self.sync_patch.stop()
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_get_tasks_defaults_to_high_and_supports_later_and_all_priority_scopes(self) -> None:
        rows = [
            ("低1", "Now", "2026-07-20", "Low"),
            ("中1", "Now", "2026-07-21", "Mid"),
            ("高・期限なし", "Now", None, "High"),
            ("高・期限あり", "Now", "2026-08-01", "High"),
            ("未設定", "Now", "2026-07-19", None),
            ("低2", "Now", None, "Low"),
            ("中2", "Now", None, "Mid"),
            ("低3", "Now", "2026-07-22", "Low"),
            ("中3", "Now", "2026-07-23", "Mid"),
            ("低4", "Now", "2026-07-24", "Low"),
            ("中4", "Now", "2026-07-25", "Mid"),
            ("低5", "Now", "2026-07-26", "Low"),
        ]
        with db.get_connection() as conn:
            conn.executemany(
                "INSERT INTO tasks_cache (source, title, status, due_date, priority, updated_at) "
                "VALUES ('notion', ?, ?, ?, ?, ?)",
                [(title, status, due_date, priority, db.now_iso()) for title, status, due_date, priority in rows],
            )

        high_result = json.loads(tools.dispatch("get_tasks", {"limit": 3}))
        later_result = json.loads(tools.dispatch("get_tasks", {"priority": "later", "limit": 3}))
        all_result = json.loads(tools.dispatch("get_tasks", {"priority": "all", "limit": 3}))

        self.assertEqual(high_result["total_count"], 2)
        self.assertFalse(high_result["has_more"])
        self.assertEqual(
            [task["title"] for task in high_result["tasks"]],
            ["高・期限あり", "高・期限なし"],
        )
        self.assertEqual(high_result["filters"]["priority"], "high")
        self.assertTrue(high_result["filters"]["priority_defaulted"])

        self.assertEqual(later_result["total_count"], 9)
        self.assertTrue(later_result["has_more"])
        self.assertEqual(
            [task["title"] for task in later_result["tasks"]],
            ["中1", "中3", "中4"],
        )
        self.assertEqual(later_result["filters"]["priority"], "later")

        self.assertEqual(all_result["total_count"], 12)
        self.assertTrue(all_result["has_more"])
        self.assertEqual(
            [task["title"] for task in all_result["tasks"]],
            ["高・期限あり", "高・期限なし", "中1"],
        )
        self.assertIn("priority=high", all_result["response_guidance"])
        self.assertIn("priority=later", all_result["response_guidance"])
        self.assertIn("priority=all", all_result["response_guidance"])



    def test_create_task_defaults_to_high_and_keeps_due_date_empty(self) -> None:
        with patch.object(config, "notion_configured", return_value=False):
            result = json.loads(tools.dispatch("create_task", {"title": "期限なしタスク"}))

        self.assertTrue(result["created"])
        self.assertEqual(result["task"]["priority"], "High")
        self.assertIsNone(result["task"]["due_date"])

    def test_frontend_accepts_shitehoshii_as_pending_action_approval(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = (root / "frontend" / "action_confirm.js").read_text(encoding="utf-8")
        html = (root / "frontend" / "legacy.html").read_text(encoding="utf-8")

        self.assertIn('"してほしい"', script)
        self.assertIn('event.stopImmediatePropagation()', script)
        self.assertIn('target.click()', script)
        self.assertIn('/static/action_confirm.js', html)


if __name__ == "__main__":
    unittest.main()
