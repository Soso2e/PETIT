from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import config, db, tools
from backend.tools import task_reads


class TaskCancelStatusTests(unittest.TestCase):
    def setUp(self) -> None:
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
        self._insert_tasks()

    def tearDown(self) -> None:
        self.sync_patch.stop()
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def _insert_tasks(self) -> None:
        rows = [
            ("企画を整理", "Yet", "2026-07-23"),
            ("PETITを実装", "Now", "2026-07-24"),
            ("スマホ検証", "ready", None),
            ("完了済み", "Done", "2026-07-20"),
            ("旧キャンセル", "Chancel", "2026-07-19"),
            ("一般表記キャンセル", "Cancelled", None),
        ]
        with db.get_connection() as conn:
            conn.executemany(
                "INSERT INTO tasks_cache (source, title, status, due_date, updated_at) "
                "VALUES ('notion', ?, ?, ?, ?)",
                [(title, status, due_date, db.now_iso()) for title, status, due_date in rows],
            )

    @staticmethod
    def _dispatch(arguments: dict[str, object]) -> dict[str, object]:
        return json.loads(tools.dispatch("get_tasks", arguments))

    def test_default_status_returns_only_active_tasks_and_separates_counts(self) -> None:
        result = self._dispatch({"priority": "all", "limit": 2})

        self.assertEqual(result["returned_count"], 2)
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["total_count"], 3)
        self.assertTrue(result["has_more"])
        self.assertEqual([task["status"] for task in result["tasks"]], ["Yet", "Now"])
        self.assertTrue(result["filters"]["active_only"])
        self.assertEqual(result["status_summary"]["active"], 3)
        self.assertEqual(result["status_summary"]["completed"], 1)
        self.assertEqual(result["status_summary"]["cancelled"], 2)
        self.assertEqual(
            result["status_summary"]["cancelled_statuses"],
            ["Cancelled", "Chancel"],
        )

    def test_all_and_explicit_cancel_status_remain_available(self) -> None:
        all_result = self._dispatch({"status": "all", "priority": "all", "limit": 20})
        cancelled_result = self._dispatch(
            {"status": "Chancel", "priority": "all", "limit": 20}
        )

        self.assertEqual(all_result["total_count"], 6)
        self.assertEqual(all_result["returned_count"], 6)
        self.assertFalse(all_result["has_more"])
        self.assertFalse(all_result["filters"]["active_only"])
        self.assertEqual(cancelled_result["total_count"], 1)
        self.assertEqual(cancelled_result["tasks"][0]["title"], "旧キャンセル")

    def test_tool_contract_tells_model_how_to_describe_counts_priorities_and_cancelled_tasks(self) -> None:
        schema = next(
            item["function"]
            for item in tools.openai_tools_schema()
            if item["function"]["name"] == "get_tasks"
        )
        result = self._dispatch({"priority": "all", "limit": 10})

        self.assertIn("total_count", schema["description"])
        self.assertIn("has_more", schema["description"])
        self.assertIn("returned_countだけを全件数と断定しない", schema["description"])
        self.assertIn("キャンセルを進行中として扱わず", schema["description"])
        self.assertIn("Priority=High", schema["description"])
        self.assertIn("priority=later", schema["description"])
        self.assertIn("priority=all", schema["description"])
        self.assertEqual(
            schema["parameters"]["properties"]["priority"]["default"],
            "high",
        )
        self.assertIn("全件数と断定しない", result["response_guidance"])
        self.assertIn("キャンセルは進行中・未完了に数えず", result["response_guidance"])


if __name__ == "__main__":
    unittest.main()
