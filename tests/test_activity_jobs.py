"""Activity read projection contract (#372): no secrets and no delivery mutation."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import Response

from backend import config, db, support_api


class ActivityJobTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        patched = patch.object(config, "DB_PATH", Path(temporary.name) / "activity.db")
        patched.start()
        self.addCleanup(patched.stop)
        db.init_db()

    def test_activity_includes_pending_and_completed_without_raw_payloads(self):
        finished = db.create_job("background_research", '{"query":"SECRET_INPUT"}',
                                 session_id="thread-1", request_id="request-1")
        db.finish_job(finished, "SECRET_RESULT")
        failed = db.create_job("agent_followup", '{"message":"CONFIDENTIAL"}',
                               session_id="thread-2", request_id="request-2")
        db.fail_job(failed, "SECRET_EXCEPTION")
        pending = db.create_job("background_research", '{}',
                                session_id="thread-3", request_id="request-3")
        response = Response()
        data = support_api.activity_jobs(response, limit=20)
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")
        self.assertEqual(data["counts"], {"queued": 1, "running": 0, "done": 1, "failed": 1})
        self.assertEqual([row["id"] for row in data["jobs"]], [pending, failed, finished])
        self.assertEqual(data["jobs"][0]["status"], "queued")
        self.assertFalse(data["coding_jobs_included"])
        self.assertTrue(data["running_is_persisted_state"])
        for row in data["jobs"]:
            self.assertEqual(set(row), {"id", "type", "status", "session_id", "request_id",
                                        "created_at", "updated_at", "claimed_at", "delivered"})
            self.assertNotIn("SECRET", str(row))
        db.mark_jobs_delivered([finished], session_id="thread-1")
        self.assertEqual(db.list_job_activity(10)[-1]["delivered"], 1)

    def test_running_is_not_claimed_as_verified_live_worker(self):
        item = db.create_job("background_research", "{}", session_id="t", request_id="r")
        claim = db.claim_next_job()
        self.assertEqual(claim["id"], item)
        response = Response()
        result = support_api.activity_jobs(response, limit=1)
        self.assertEqual(result["jobs"][0]["status"], "running")
        self.assertTrue(result["running_is_persisted_state"])

    def test_limit_is_bounded(self):
        for i in range(110):
            db.create_job("background_research", "{}", request_id=str(i))
        self.assertEqual(len(db.list_job_activity(10000)), 100)
        self.assertEqual(len(db.list_job_activity(-10)), 1)


if __name__ == "__main__":
    unittest.main()
