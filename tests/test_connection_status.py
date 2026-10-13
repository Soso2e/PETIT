from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from fastapi import FastAPI

from backend import config, connection_status as connections, db, health, task_sync_queue


class ConnectionStatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config_patch = patch.object(config, "DB_PATH", Path(self.tmp.name) / "petit.sqlite3")
        self.config_patch.start()
        db.init_db()
        self.app = FastAPI()
        self.app.include_router(health.router)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.config_patch.stop()
        self.tmp.cleanup()

    def service(self, name):
        return next(s for s in self.client.get("/api/connections").json()["services"] if s["id"] == name)

    def queue(self, status="failed", attempts=3):
        task_sync_queue.ensure_task_sync_schema()
        with db.get_connection() as conn:
            task_id = conn.execute("INSERT INTO tasks_cache(source, external_id, title, status, updated_at) "
                                   "VALUES ('notion', 'page', '音声修正', 'Yet', ?)", (db.now_iso(),)).lastrowid
            conn.execute("INSERT INTO task_sync_queue(task_id, operation, status, attempts, last_error, "
                         "next_attempt_at, created_at, updated_at) VALUES (?, 'update', ?, ?, ?, ?, ?, ?)",
                         (task_id, status, attempts, "Notion API 403 Forbidden token=super-secret", db.now_iso(), db.now_iso(), db.now_iso()))
        return task_id

    def test_open_does_not_contact_any_provider(self):
        with patch.object(connections, "_probe", side_effect=AssertionError("network")) as probe, patch("httpx.Client.send", side_effect=AssertionError("network")), patch("httpx.get", side_effect=AssertionError("network")):
            data = connections.snapshot()
        self.assertEqual(len(data["services"]), 7)
        probe.assert_not_called()
        self.assertNotIn("connected", [s["connection_status"] for s in data["services"]])

    def test_unconfigured_never_normal_even_with_history(self):
        db.record_sync_success("github:repo:owner/repo", 1)
        with patch.object(connections.github_config, "configured", return_value=False):
            service = self.service("github")
        self.assertEqual(service["connection_status"], "unconfigured")
        self.assertEqual(service["sync_status"], "unconfigured")
        self.assertFalse(service["can_check"])

    def test_connection_success_does_not_claim_sync_success_and_is_cached(self):
        with patch.object(connections, "_configured", return_value=True), patch.object(connections, "_probe") as probe:
            first = self.client.post("/api/connections/github/check").json()
            self.client.post("/api/connections/github/check")
            service = self.service("github")
        self.assertEqual(first["connection_status"], "connected")
        self.assertEqual(service["sync_status"], "unverified")
        self.assertIsNotNone(service["last_connection_success_at"])
        self.assertIsNone(service["last_sync_success_at"])
        self.assertEqual(probe.call_count, 1)

    def test_http_error_redacts_body_and_isolated_from_other_services(self):
        response = httpx.Response(403, request=httpx.Request("GET", "https://example.org?token=secret"), text="super-secret")
        exc = httpx.HTTPStatusError("super-secret", request=response.request, response=response)
        with patch.object(connections, "_configured", return_value=True), patch.object(connections, "_probe", side_effect=exc):
            service = self.client.post("/api/connections/github/check").json()
        self.assertEqual(service["connection_status"], "error")
        self.assertEqual(service["error_code"], "403")
        self.assertNotIn("super-secret", json.dumps(service))
        self.assertIn("共有", service["error"])
        self.assertEqual(len(self.client.get("/api/connections").json()["services"]), 7)

    def test_queue_failure_metadata_and_retry_limit(self):
        self.queue(attempts=5)
        with patch.object(config, "notion_configured", return_value=True):
            service = self.service("notion")
        operation = service["operations"][0]
        self.assertEqual(service["sync_status"], "error")
        self.assertEqual(service["failed_count"], 1)
        self.assertEqual(operation["title"], "音声修正")
        self.assertEqual(operation["error_code"], "403")
        self.assertIsNone(operation["next_attempt_at"])
        self.assertIsNone(operation["last_attempt_at"])
        self.assertNotIn("super-secret", json.dumps(service))

    def test_claim_records_real_attempt_time_and_retry_preserves_it(self):
        task_id = self.queue(status="pending")
        claimed = task_sync_queue._claim_next()
        with db.get_connection() as conn:
            at = conn.execute("SELECT last_attempt_at FROM task_sync_queue WHERE id=?", (claimed["id"],)).fetchone()[0]
        self.assertIsNotNone(at)
        task_sync_queue._mark_failed(claimed, RuntimeError("failed"))
        task_sync_queue.retry_task(task_id)
        operations, _ = connections._notion_operations()
        self.assertEqual(operations[0]["last_attempt_at"], at)

    def test_old_cache_and_partial_failure(self):
        at = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        db.record_sync_success("github:repo:owner/repo", 1)
        with db.get_connection() as conn:
            conn.execute("UPDATE sync_state SET last_success_at=?", (at,))
        with patch.object(connections, "_configured", return_value=True):
            self.assertEqual(self.service("github")["sync_status"], "stale")
        original = connections._service
        with patch.object(connections, "_service", side_effect=lambda name: (_ for _ in ()).throw(RuntimeError("secret")) if name == "notion" else original(name)):
            data = self.client.get("/api/connections").json()
        self.assertEqual(len(data["services"]), 7)
        self.assertNotIn("secret", json.dumps(data))

    def test_conflict_never_exposes_retry_schedule(self):
        self.queue(status="conflict")
        with patch.object(config, "notion_configured", return_value=True):
            service = self.service("notion")
        self.assertEqual(service["sync_status"], "conflict")
        self.assertIsNone(service["operations"][0]["next_attempt_at"])

    def test_redacts_configured_and_generic_secrets(self):
        with patch.object(config, "NOTION_API_KEY", "opaque-value"):
            text = connections.safe_text('opaque-value Bearer abc password=pwd https://host/private ghp_abc "token":"xyz"')
        for secret in ["opaque-value", "abc", "pwd", "https://host", "ghp_abc", "xyz"]:
            self.assertNotIn(secret, text)

    def test_unknown_unconfigured_and_concurrent_probe(self):
        self.assertEqual(self.client.post("/api/connections/unknown/check").status_code, 404)
        with patch.object(connections, "_configured", return_value=False):
            self.assertEqual(self.client.post("/api/connections/notion/check").status_code, 409)
        connections._LOCKS["github"].acquire()
        try:
            with patch.object(connections, "_configured", return_value=True):
                self.assertEqual(self.client.post("/api/connections/github/check").status_code, 409)
        finally:
            connections._LOCKS["github"].release()


if __name__ == "__main__":
    unittest.main()
