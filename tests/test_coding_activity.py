"""Read-only Coding Job Activity status contract, without goal/path leakage."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import coding_api, coding_jobs, config, db


class CodingActivityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "petit.db"
        patcher = patch.object(config, "DB_PATH", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        db.init_db()

    def add(self, n: int, status: str = "queued") -> None:
        with db.get_connection() as connection:
            connection.execute(
                "INSERT INTO coding_jobs(id,request_id,input_hash,task_id,project_id,"
                "repository,base_commit,provider,model,goal,status,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"job-{n}", f"request-{n}", f"sha-{n}", n, "prj", "/SECRET/PATH",
                 "a" * 40, "codex", "model", "SECRET_GOAL", status,
                 f"2026-11-03T00:{n % 60:02d}:00Z", f"2026-11-03T00:{n % 60:02d}:00Z"),
            )

    def test_not_initialized_does_not_create_table_or_backup(self):
        value = coding_jobs.activity_summary()
        self.assertEqual(value, {"initialized": False, "jobs": []})
        self.assertFalse(Path(str(self.path) + ".before-coding-jobs.bak").exists())
        with db.get_connection() as connection:
            self.assertFalse(connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='coding_jobs'"
            ).fetchone())

    def test_readonly_projection_keeps_raw_goal_and_path_private(self):
        coding_jobs.ensure_schema()
        self.add(1, "running")
        self.add(2, "ready_for_review")
        result = coding_api.activity(limit=30)
        self.assertTrue(result["initialized"])
        self.assertEqual(result["jobs"][0]["status"], "ready_for_review")
        self.assertEqual(result["jobs"][1]["status"], "running")
        self.assertEqual(set(result["jobs"][0]), {
            "id", "task_id", "project_id", "provider", "status", "created_at", "updated_at"
        })
        self.assertNotIn("SECRET_GOAL", str(result))
        self.assertNotIn("SECRET/PATH", str(result))
        with db.get_connection() as connection:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM coding_jobs").fetchone()[0], 2)

    def test_limit_bounded_and_no_side_effects(self):
        coding_jobs.ensure_schema()
        for n in range(105):
            self.add(n)
        self.assertEqual(len(coding_jobs.activity_summary(10000)["jobs"]), 100)
        self.assertEqual(len(coding_jobs.activity_summary(-1)["jobs"]), 1)


if __name__ == "__main__":
    unittest.main()
