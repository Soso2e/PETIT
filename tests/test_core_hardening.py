from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import briefing, config, db, notion_project_sync, request_context, summarizer, support_api
from backend.tools.builtins import register_builtin_tools


class RoutingAndMemoryHardeningTests(unittest.TestCase):






    def test_briefing_prefers_episode_context_over_legacy_summary(self) -> None:
        with (
            patch.object(briefing.db, "recent_episodes", return_value=[{"title": "PETIT", "summary": "Agent経路を修正した"}]),
            patch.object(briefing.db, "recent_summaries", return_value=[{"summary": "古い要約"}]) as legacy,
        ):
            context = briefing._recent_context(2)

        legacy.assert_not_called()
        self.assertEqual(context[0]["title"], "PETIT")
        self.assertEqual(context[0]["summary"], "Agent経路を修正した")


class PersistenceHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "petit.sqlite3"
        self.db_patch = patch.object(config, "DB_PATH", self.db_path)
        self.db_patch.start()
        db.init_db()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.tmp.cleanup()

    def test_sqlite_wal_busy_timeout_and_session_history(self) -> None:
        with db.get_connection() as conn:
            self.assertEqual(str(conn.execute("PRAGMA journal_mode").fetchone()[0]).casefold(), "wal")
            self.assertGreaterEqual(int(conn.execute("PRAGMA busy_timeout").fetchone()[0]), 5000)

        db.save_conversation("s1 user", "s1 reply", session_id="s1")
        db.save_conversation("s2 user", "s2 reply", session_id="s2")
        self.assertEqual([row["user_text"] for row in db.recent_conversations(session_id="s1")], ["s1 user"])

    def test_jobs_are_bound_to_session_and_acknowledged_explicitly(self) -> None:
        with request_context.bind(request_id="req-1", session_id="s1"):
            first = db.create_job("background_research", "{}")
        with request_context.bind(request_id="req-2", session_id="s2"):
            second = db.create_job("background_research", "{}")
        db.finish_job(first, "one")
        db.finish_job(second, "two")

        rows = support_api.jobs(limit=10, session_id="s1")["jobs"]
        self.assertEqual([row["id"] for row in rows], [first])
        self.assertEqual([row["id"] for row in support_api.jobs(limit=10, session_id="s1")["jobs"]], [first])

        acknowledged = support_api.acknowledge_jobs(support_api.JobAck(job_ids=[first], session_id="s1"))
        self.assertEqual(acknowledged["acknowledged"], 1)
        self.assertEqual(support_api.jobs(limit=10, session_id="s1")["jobs"], [])
        self.assertEqual([row["id"] for row in support_api.jobs(limit=10, session_id="s2")["jobs"]], [second])

    def test_successful_notion_task_sync_replaces_removed_rows(self) -> None:
        first = [
            {"external_id": "task-a", "title": "A", "status": "Yet"},
            {"external_id": "task-b", "title": "B", "status": "Yet"},
        ]
        notion_project_sync.upsert_tasks(first)
        notion_project_sync.upsert_tasks([{"external_id": "task-b", "title": "B updated", "status": "Now"}])

        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT external_id, title, status FROM tasks_cache WHERE source='notion' ORDER BY external_id"
            ).fetchall()
        self.assertEqual([dict(row) for row in rows], [{"external_id": "task-b", "title": "B updated", "status": "Now"}])


if __name__ == "__main__":
    unittest.main()
