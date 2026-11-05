"""Durable read task regression tests (#372 P0)."""
from __future__ import annotations

import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from backend import config, conversation_store, db, durable_reads


class DurableReadTaskTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        override = patch.object(config, "DB_PATH", Path(temp.name) / "reads.db")
        override.start()
        self.addCleanup(override.stop)
        db.init_db()
        conversation_store.create_thread("thread-a")
        conversation_store.create_thread("private-a", privacy="local_only")
        durable_reads.ensure_schema()

    def enqueue(self, request_id="request-a", query="AI news"):
        return durable_reads.enqueue(
            thread_id="thread-a", request_id=request_id, kind="news", query=query
        )

    def test_create_and_retry_do_not_duplicate(self):
        first = self.enqueue()
        retry = self.enqueue()
        self.assertEqual(first["id"], retry["id"])
        self.assertEqual(first["status"], "queued")
        self.assertEqual(len(durable_reads.listing()), 1)
        with self.assertRaisesRegex(ValueError, "idempotency_conflict"):
            self.enqueue(query="unrelated")
        self.assertEqual(len(durable_reads.listing()), 1)

    def test_private_thread_rejects_external_reads(self):
        with self.assertRaisesRegex(ValueError, "local_only"):
            durable_reads.enqueue(
                thread_id="private-a", request_id="private-1",
                kind="news", query="secret",
            )

    def test_old_worker_cannot_claim_new_durable_job(self):
        self.enqueue()
        self.assertIsNone(db.claim_next_job())
        legacy = db.create_job("background_research", '{"kind":"news","query":"legacy"}')
        self.assertEqual(db.claim_next_job()["id"], legacy)
        self.assertIsNotNone(durable_reads.claim())

    def test_cancel_queued_and_running_is_fenced(self):
        queued = self.enqueue()
        self.assertEqual(durable_reads.cancel(queued["id"])["status"], "cancelled")
        self.assertIsNone(durable_reads.claim())
        other = self.enqueue("another-request")
        token = durable_reads.claim()
        self.assertEqual(token["id"], other["id"])
        self.assertEqual(durable_reads.cancel(other["id"])["status"], "cancelled")
        self.assertFalse(durable_reads.finish(other["id"], token["token"], result="late"))
        self.assertIsNone(durable_reads.get(other["id"])["result"])

    def test_expired_lease_retries_only_read_and_fences_previous_worker(self):
        created = self.enqueue()
        first = durable_reads.claim(lease_seconds=3)
        with db.get_connection() as conn:
            conn.execute(
                "UPDATE jobs SET lease_expires_at=? WHERE id=?",
                (time.time() - 1, created["id"]),
            )
        second = durable_reads.claim(lease_seconds=3)
        self.assertEqual(first["id"], second["id"])
        self.assertNotEqual(first["token"], second["token"])
        self.assertFalse(durable_reads.finish(created["id"], first["token"], result="stale"))
        self.assertTrue(durable_reads.finish(created["id"], second["token"], result="good"))
        saved = durable_reads.get(created["id"])
        self.assertEqual(saved["status"], "done")
        self.assertEqual(saved["result"], "good")
        self.assertEqual(saved["attempt_count"], 2)

    def test_exhausted_abandoned_read_does_not_run_forever(self):
        created = self.enqueue()
        with db.get_connection() as conn:
            conn.execute(
                "UPDATE jobs SET status='running',attempt_count=3,"
                "lease_expires_at=? WHERE id=?",
                (time.time() - 1, created["id"]),
            )
        self.assertIsNone(durable_reads.claim())
        item = durable_reads.get(created["id"])
        self.assertEqual(item["status"], "failed")
        self.assertEqual(item["error_code"], "read_task_attempts_exhausted")

    def test_parallel_claim_only_one_winner(self):
        created = self.enqueue()
        barrier = threading.Barrier(2)

        def take():
            barrier.wait(timeout=3)
            return durable_reads.claim()

        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(take)
            b = pool.submit(take)
            selected = [x for x in (a.result(), b.result()) if x is not None]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["id"], created["id"])

    def test_read_process_persists_result_and_notification(self):
        created = self.enqueue()
        current = durable_reads.claim()
        with patch.object(durable_reads, "_research", return_value="verified public news"), \
             patch("backend.notifications.dispatch_notification") as notify:
            durable_reads.process_once(current, lease_seconds=3)
        self.assertEqual(durable_reads.get(created["id"])["result"], "verified public news")
        notify.assert_called_once()
        self.assertEqual(notify.call_args.kwargs["category"], "background_task")

    def test_activity_does_not_include_query_or_result(self):
        created = self.enqueue(query="PRIVATE_QUERY")
        rows = durable_reads.listing()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], created["id"])
        self.assertNotIn("PRIVATE_QUERY", str(rows))
        self.assertNotIn("input_json", rows[0])
        self.assertNotIn("claimed_by", rows[0])


if __name__ == "__main__":
    unittest.main()
