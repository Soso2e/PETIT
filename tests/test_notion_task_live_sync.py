from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import config, db, notion_client, notion_task_sync, task_sync_queue
from backend.tools import task_reads


class NotionTaskLiveSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [
            patch.object(config, "DB_PATH", Path(self.tmp.name) / "petit.sqlite3"),
            patch.object(config, "NOTION_API_KEY", "secret_test"),
            patch.object(config, "NOTION_TASKS_DB_ID", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
            patch.object(config, "NOTION_TASKS_DATA_SOURCE_ID", ""),
            patch.object(config, "NOTION_WEBHOOK_ENDPOINT_SECRET", ""),
            patch.object(config, "NOTION_WEBHOOK_VERIFICATION_TOKEN", ""),
            patch.object(config, "NOTION_WEBHOOK_REQUIRE_SIGNATURE", True),
            patch.object(config, "NOTION_WEBHOOK_ALLOW_TOKEN_ROTATION", False),
            patch.object(config, "NOTION_TASK_BACKGROUND_SYNC_ENABLED", True),
            patch.object(config, "NOTION_TASK_SYNC_ON_STARTUP", True),
            patch.object(config, "NOTION_TASK_PULL_INTERVAL_SECONDS", 300.0),
            patch.object(config, "NOTION_TASK_FULL_SYNC_INTERVAL_SECONDS", 86400.0),
            patch.object(config, "NOTION_TASK_SYNC_OVERLAP_SECONDS", 120.0),
        ]
        for item in self.patches:
            item.start()
        db.init_db()
        notion_task_sync.ensure_schema()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    @staticmethod
    def remote(
        *,
        external_id: str = "task-1",
        title: str = "卒研資料",
        due_date: str | None = "2026-07-25",
        priority: str | None = "Mid",
        source_updated_at: str = "2026-07-23T10:00:00.000Z",
        archived: bool = False,
    ) -> dict[str, object]:
        return {
            "external_id": external_id,
            "title": title,
            "status": "Yet",
            "due_date": due_date,
            "priority": priority,
            "category": "Sch",
            "area": "university",
            "reason": None,
            "url": f"https://notion.so/{external_id}",
            "done_date": None,
            "project_external_ids": [],
            "assignee_external_ids": [],
            "parent_external_ids": [],
            "subtask_external_ids": [],
            "summary": None,
            "source_updated_at": source_updated_at,
            "archived": archived,
        }

    def test_webhook_signature_and_duplicate_event_are_idempotent(self) -> None:
        stored = notion_task_sync.accept_verification_token("verify-secret")
        self.assertTrue(stored["accepted"])
        payload = {
            "id": "event-1",
            "timestamp": "2026-07-23T10:00:00.000Z",
            "type": "page.properties_updated",
            "entity": {"id": "task-1", "type": "page"},
        }
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        signature = "sha256=" + hmac.new(b"verify-secret", raw, hashlib.sha256).hexdigest()
        self.assertTrue(notion_task_sync.verify_webhook_signature(raw, signature))
        self.assertFalse(notion_task_sync.verify_webhook_signature(raw, "sha256=bad"))

        first = notion_task_sync.enqueue_webhook_event(payload)
        second = notion_task_sync.enqueue_webhook_event(payload)
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        with db.get_connection() as conn:
            count = int(conn.execute("SELECT COUNT(*) FROM notion_task_inbox").fetchone()[0])
        self.assertEqual(count, 1)

    def test_non_overlapping_remote_change_auto_merges_with_pending_local_edit(self) -> None:
        base = self.remote()
        self.assertEqual(notion_task_sync.merge_remote_task(base), "inserted")
        with db.get_connection() as conn:
            row = conn.execute("SELECT id FROM tasks_cache WHERE external_id='task-1'").fetchone()
            task_id = int(row["id"])
            conn.execute(
                "UPDATE tasks_cache SET priority='High', sync_status='pending' WHERE id=?",
                (task_id,),
            )
            conn.execute(
                "INSERT INTO task_sync_queue "
                "(task_id, provider, operation, payload_json, base_source_updated_at, status, attempts, next_attempt_at, created_at, updated_at) "
                "VALUES (?, 'notion', 'update', ?, ?, 'pending', 0, ?, ?, ?)",
                (
                    task_id,
                    json.dumps({"priority": "High"}),
                    base["source_updated_at"],
                    db.now_iso(),
                    db.now_iso(),
                    db.now_iso(),
                ),
            )

        incoming = self.remote(due_date="2026-07-28", source_updated_at="2026-07-23T11:00:00.000Z")
        self.assertEqual(notion_task_sync.merge_remote_task(incoming), "merged")
        with db.get_connection() as conn:
            task = conn.execute(
                "SELECT due_date, priority, sync_status FROM tasks_cache WHERE id=?",
                (task_id,),
            ).fetchone()
            operation = conn.execute(
                "SELECT base_source_updated_at FROM task_sync_queue WHERE task_id=?",
                (task_id,),
            ).fetchone()
        self.assertEqual(task["due_date"], "2026-07-28")
        self.assertEqual(task["priority"], "High")
        self.assertEqual(task["sync_status"], "pending")
        self.assertEqual(operation["base_source_updated_at"], "2026-07-23T11:00:00.000Z")

    def test_same_field_change_becomes_conflict_and_keeps_remote_snapshot(self) -> None:
        base = self.remote(title="卒研資料")
        notion_task_sync.merge_remote_task(base)
        with db.get_connection() as conn:
            row = conn.execute("SELECT id FROM tasks_cache WHERE external_id='task-1'").fetchone()
            task_id = int(row["id"])
            conn.execute(
                "UPDATE tasks_cache SET title='PETIT側タイトル', sync_status='pending' WHERE id=?",
                (task_id,),
            )

        incoming = self.remote(title="Notion側タイトル", source_updated_at="2026-07-23T12:00:00.000Z")
        self.assertEqual(notion_task_sync.merge_remote_task(incoming), "conflict")
        with db.get_connection() as conn:
            task = conn.execute(
                "SELECT title, sync_status, sync_error, remote_snapshot_json FROM tasks_cache WHERE id=?",
                (task_id,),
            ).fetchone()
        self.assertEqual(task["title"], "PETIT側タイトル")
        self.assertEqual(task["sync_status"], "conflict")
        self.assertIn("title", task["sync_error"])
        self.assertEqual(json.loads(task["remote_snapshot_json"])["title"], "Notion側タイトル")

    def test_webhook_inbox_fetches_only_task_database_page(self) -> None:
        payload = {
            "id": "event-page",
            "timestamp": "2026-07-23T10:00:00.000Z",
            "type": "page.properties_updated",
            "entity": {"id": "task-2", "type": "page"},
        }
        notion_task_sync.enqueue_webhook_event(payload)
        raw_page = {"parent": {"database_id": config.NOTION_TASKS_DB_ID}}
        remote = self.remote(external_id="task-2", title="Webhook追加")
        with patch.object(notion_client, "_get", return_value=raw_page), patch.object(
            notion_client, "parse_task_page", return_value=remote
        ):
            self.assertTrue(notion_task_sync.process_inbox_next())
        with db.get_connection() as conn:
            task = conn.execute("SELECT title FROM tasks_cache WHERE external_id='task-2'").fetchone()
            event = conn.execute("SELECT status FROM notion_task_inbox WHERE event_id='event-page'").fetchone()
        self.assertEqual(task["title"], "Webhook追加")
        self.assertEqual(event["status"], "done")

    def test_full_reconcile_marks_missing_remote_task_deleted_without_removing_row(self) -> None:
        notion_task_sync.merge_remote_task(self.remote(external_id="missing-task"))
        with patch.object(notion_client, "query_tasks_database_v2", return_value=[]):
            result = notion_task_sync.sync_now("full")
        self.assertTrue(result["ok"])
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT remote_deleted_at FROM tasks_cache WHERE external_id='missing-task'"
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertTrue(row["remote_deleted_at"])

    def test_get_tasks_reads_sqlite_without_calling_notion(self) -> None:
        notion_task_sync.merge_remote_task(self.remote())
        with patch.object(notion_client, "query_tasks_database_v2", side_effect=AssertionError("network called")) as query:
            result = task_reads.get_tasks(priority="all")
        query.assert_not_called()
        self.assertEqual(result["returned_count"], 1)
        self.assertEqual(result["tasks"][0]["title"], "卒研資料")
        self.assertEqual(result["sync"]["mode"], "local_first_outbox_inbox")


if __name__ == "__main__":
    unittest.main()
