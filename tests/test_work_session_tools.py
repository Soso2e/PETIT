from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import config, db, tools, work_sessions


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


    def test_start_same_paused_task_resumes_instead_of_reporting_already_active(self) -> None:
        task_id = self.add_task("HERE")
        started = self.dispatch("start_work_session", {"task_id": str(task_id)})
        self.dispatch("update_work_session", {"action": "pause"})
        resumed = self.dispatch("start_work_session", {"task_id": str(task_id)})
        self.assertTrue(resumed["resumed"])
        self.assertFalse(resumed["started"])
        self.assertEqual(resumed["session"]["status"], "active")
        self.assertEqual(resumed["session"]["session_id"], started["session"]["session_id"])
        repeated = self.dispatch("start_work_session", {"task_id": str(task_id)})
        self.assertTrue(repeated["already_active"])

    def test_resume_failure_does_not_claim_success(self) -> None:
        task_id = self.add_task("HERE")
        self.dispatch("start_work_session", {"task_id": str(task_id)})
        self.dispatch("update_work_session", {"action": "pause"})
        with patch("backend.work_sessions.start_session", return_value={}):
            result = self.dispatch("start_work_session", {"task_id": str(task_id)})
        self.assertFalse(result["resumed"])
        self.assertFalse(result["started"])
        self.assertFalse(result["already_active"])
        self.assertNotIn("session", result)


if __name__ == "__main__":
    unittest.main()
