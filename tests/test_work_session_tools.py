from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import capability_router, config, db, tools, work_sessions


class WorkSessionToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(config, "DB_PATH", Path(self.temp_dir.name) / "petit.db")
        self.db_patch.start()
        db.init_db()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def add_task(self, title: str, external_id: str | None = None) -> int:
        with db.get_connection() as conn:
            row = conn.execute(
                "INSERT INTO tasks_cache(source, title, status, external_id, updated_at) "
                "VALUES ('notion', ?, 'todo', ?, ?)",
                (title, external_id, db.now_iso()),
            )
            return int(row.lastrowid)

    def dispatch(self, name: str, arguments: dict | None = None) -> dict:
        return json.loads(tools.dispatch(name, arguments or {}))

    def test_start_resolves_one_existing_task_and_records_task_id(self) -> None:
        task_id = self.add_task("PETITの作業記録を実装", "notion-page-1")

        result = self.dispatch("start_work_session", {"task": "作業記録"})

        self.assertTrue(result["started"])
        self.assertEqual(result["session"]["task_id"], str(task_id))
        self.assertEqual(result["session"]["task"], "PETITの作業記録を実装")
        self.assertEqual(result["session"]["elapsed_seconds"], 0)

    def test_start_does_not_guess_when_multiple_tasks_match(self) -> None:
        self.add_task("PETITの作業記録を実装")
        self.add_task("Mayaの作業記録を実装")

        result = self.dispatch("start_work_session", {"task": "作業記録"})

        self.assertFalse(result["started"])
        self.assertEqual(len(result["candidates"]), 2)
        self.assertIsNone(work_sessions.active_session())

    def test_pause_resume_and_end_current_session(self) -> None:
        task_id = self.add_task("集中する")
        started = self.dispatch("start_work_session", {"task_id": str(task_id)})
        self.assertTrue(started["started"])

        paused = self.dispatch("update_work_session", {"action": "pause"})
        resumed = self.dispatch("update_work_session", {"action": "resume"})
        ended = self.dispatch("update_work_session", {"action": "end"})

        self.assertEqual(paused["session"]["status"], "paused")
        self.assertEqual(resumed["session"]["status"], "active")
        self.assertEqual(ended["session"]["status"], "ended")
        self.assertIsNone(work_sessions.active_session())

    def test_work_tools_have_expected_risk_and_capability(self) -> None:
        names = capability_router.tool_names_for(["work_sessions"])
        self.assertIn("get_work_status", names)
        self.assertIn("get_work_report", names)
        self.assertIn("start_work_session", names)
        self.assertIn("update_work_session", names)
        self.assertEqual(tools.risk_for("start_work_session"), "low_risk_write")
        self.assertEqual(tools.risk_for("update_work_session"), "low_risk_write")


class WorkSessionRoutingTests(unittest.TestCase):
    def test_work_time_question_cannot_bypass_tools(self) -> None:
        with patch.object(
            capability_router,
            "chat_completion",
            return_value={"content": "今日は60分作業したよ。", "tool_calls": []},
        ):
            route = capability_router.choose("今日どれに何分作業した？", history=[])

        self.assertEqual(route["type"], "agent")
        self.assertIn("work_sessions", route["capabilities"])
        self.assertEqual(route["source"], "forced_tool_guard")


if __name__ == "__main__":
    unittest.main()
