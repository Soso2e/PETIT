import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import config, db, task_conflict_resolution as resolution, task_sync_queue, task_hierarchy, notification_center
from backend.notion_client import NotionError


class ConflictResolutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config_patch = patch.object(config, "DB_PATH", Path(self.tmp.name) / "fixture.db")
        self.config_patch.start(); db.init_db(); task_hierarchy.ensure_task_hierarchy_schema(); notification_center.init_db()
        self.remote = {"external_id": "remote", "title": "Notion編集", "status": "Yet", "priority": "High", "area": "personal", "source_updated_at": "2026-10-12T02:00:00Z", "parent_external_ids": []}
        with db.get_connection() as conn:
            self.task_id = conn.execute("INSERT INTO tasks_cache(source, external_id, title, status, priority, updated_at, source_updated_at, sync_status, parent_task_id) VALUES ('notion','remote','PETIT編集','Yet','High',?,'old','conflict',999)", (db.now_iso(),)).lastrowid
            conn.execute("INSERT INTO task_sync_queue(task_id,operation,payload_json,status,created_at,updated_at) VALUES (?,'update',?,'conflict',?,?)", (self.task_id, json.dumps({"title": "PETIT編集", "parent_external_ids": ["parent"]}), db.now_iso(), db.now_iso()))
        self.remote_patch = patch.object(resolution.notion_client, "get_task_page", side_effect=lambda _: dict(self.remote))
        self.remote_patch.start()

    def tearDown(self):
        self.remote_patch.stop(); self.config_patch.stop(); self.tmp.cleanup()

    def choose(self, choice, revision=None):
        revision = revision or json.loads(resolution.preview(self.task_id).body)["revision"]
        return resolution.resolve(self.task_id, resolution.ConflictChoice(choice=choice, revision=revision))

    def test_notion_choice_cancels_queue_and_clears_local_parent_with_audit(self):
        self.assertEqual(self.choose("notion").status_code, 200)
        task = task_sync_queue._task(self.task_id)
        self.assertEqual(task["title"], "Notion編集"); self.assertEqual(task["sync_status"], "synced"); self.assertIsNone(task["parent_task_id"])
        self.assertFalse(task_sync_queue.process_next())
        with db.get_connection() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM ui_action_audit").fetchone()[0], 1)

    def test_snapshot_failure_rolls_back_choice_and_audit(self):
        from backend.notion_task_sync import merge
        with patch.object(merge, "_save_snapshot", side_effect=RuntimeError("snapshot failure")):
            with self.assertRaises(RuntimeError):
                self.choose("notion")
        task = task_sync_queue._task(self.task_id)
        self.assertEqual(task["title"], "PETIT編集")
        self.assertEqual(task["sync_status"], "conflict")
        with db.get_connection() as conn:
            self.assertEqual(conn.execute("SELECT status FROM task_sync_queue").fetchone()[0], "conflict")
            self.assertEqual(conn.execute("SELECT count(*) FROM ui_action_audit").fetchone()[0], 0)

    def test_petit_choice_preserves_payload_and_waits_for_notion_ack(self):
        self.assertEqual(self.choose("petit").status_code, 200)
        task = task_sync_queue._task(self.task_id)
        self.assertEqual(task["title"], "PETIT編集"); self.assertEqual(task["sync_status"], "pending")
        with db.get_connection() as conn:
            operation = dict(conn.execute("SELECT * FROM task_sync_queue").fetchone())
        self.assertEqual(operation["base_source_updated_at"], self.remote["source_updated_at"])
        self.assertEqual(json.loads(operation["payload_json"])["parent_external_ids"], ["parent"])
        self.remote["source_updated_at"] = "newer"
        with patch.object(task_sync_queue, "_update_remote_task") as write:
            self.assertTrue(task_sync_queue.process_next()); write.assert_not_called()
        self.assertEqual(task_sync_queue._task(self.task_id)["sync_status"], "conflict")

    def test_remote_or_local_change_requires_new_preview(self):
        revision = json.loads(resolution.preview(self.task_id).body)["revision"]
        self.remote["title"] = "さらに編集"
        self.assertEqual(self.choose("notion", revision).status_code, 409)
        revision = json.loads(resolution.preview(self.task_id).body)["revision"]
        with db.get_connection() as conn:
            conn.execute("UPDATE tasks_cache SET title='別画面で編集' WHERE id=?", (self.task_id,))
        self.assertEqual(self.choose("petit", revision).status_code, 409)
        self.assertEqual(task_sync_queue._task(self.task_id)["sync_status"], "conflict")

    def test_404_does_not_mutate_or_expose_provider_error(self):
        revision = json.loads(resolution.preview(self.task_id).body)["revision"]
        with patch.object(resolution.notion_client, "get_task_page", side_effect=NotionError("404 private-url")):
            response = self.choose("notion", revision)
        self.assertEqual(response.status_code, 503); self.assertNotIn(b"private-url", response.body)
        self.assertEqual(task_sync_queue._task(self.task_id)["sync_status"], "conflict")

    def test_duplicate_click_is_rejected(self):
        revision = json.loads(resolution.preview(self.task_id).body)["revision"]
        self.assertEqual(self.choose("notion", revision).status_code, 200)
        self.assertEqual(self.choose("notion", revision).status_code, 409)

    def test_feed_after_zero_is_ordered_and_includes_resolved_events(self):
        from backend import notifications
        ids = [notifications.dispatch_notification(category="work_session", title="確認", body="続ける？")["event_id"] for _ in range(3)]
        notification_center.update_event_state(ids[1], resolved=True)
        events = notification_center.list_events(state="all", after_id=ids[0])["events"]
        self.assertEqual([event["id"] for event in events], ids[1:])
        self.assertEqual([event["id"] for event in notification_center.list_events(state="all", after_id=0)["events"]], ids)
