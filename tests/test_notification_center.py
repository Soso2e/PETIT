from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import config, db, notification_center, notifications


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


if __name__ == "__main__":
    unittest.main()
