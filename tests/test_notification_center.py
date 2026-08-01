from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import config, db, notification_center, notifications, task_list_api


class NotificationCenterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(config, "DB_PATH", Path(self.tmp.name) / "app.db")
        self.db_patch.start()
        db.init_db()
        notifications.init_db()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.tmp.cleanup()

    def test_task_deep_link_and_state(self) -> None:
        result = notifications.dispatch_notification(
            category="high_task",
            title="期限が近いタスク",
            body="確認してください。",
            url="/?task=42",
        )
        event = notification_center.list_events()["events"][0]
        self.assertEqual(event["entity_type"], "task")
        self.assertEqual(event["entity_id"], "42")
        self.assertIn(f"notification={result['event_id']}", event["action_url"])

        notification_center.update_event_state(result["event_id"], resolved=True)
        self.assertEqual(notification_center.list_events()["events"], [])

    def test_schema_migration_is_idempotent(self) -> None:
        notifications.init_db()
        notifications.init_db()
        with db.get_connection() as conn:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(notification_events)")}
        self.assertTrue({"read_at", "resolved_at", "entity_type", "entity_id", "action_url"} <= columns)

    def test_ui_task_list_separates_high_and_low_and_excludes_mid_done(self) -> None:
        with db.get_connection() as conn:
            conn.executemany(
                "INSERT INTO tasks_cache(title, status, due_date, priority, updated_at) VALUES (?, ?, ?, ?, ?)",
                [
                    ("重要", "Yet", None, "High", db.now_iso()),
                    ("あとで", "Yet", "2099-01-01", "Low", db.now_iso()),
                    ("中間", "Yet", None, "Mid", db.now_iso()),
                    ("完了済み", "Done", None, "High", db.now_iso()),
                ],
            )

        high_response = task_list_api.list_ui_tasks(priority="high")
        low_response = task_list_api.list_ui_tasks(priority="low")
        invalid_response = task_list_api.list_ui_tasks(priority="mid")
        high = json.loads(high_response.body)
        low = json.loads(low_response.body)

        self.assertEqual([task["title"] for task in high["tasks"]], ["重要"])
        self.assertEqual([task["title"] for task in low["tasks"]], ["あとで"])
        self.assertEqual(invalid_response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
