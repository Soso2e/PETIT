from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

os.environ["PETIT_REMINDER_SCHEDULER_ENABLED"] = "0"

from backend import config, reminders  # noqa: E402


class ReminderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tempdir.name) / "petit.sqlite3")
        self.db_patch = patch.object(config, "DB_PATH", self.db_path)
        self.db_patch.start()
        reminders.ensure_schema(recover_dispatching=True)

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.tempdir.cleanup()

    def test_create_relative_reminder_and_list_it(self) -> None:
        now = datetime(2026, 8, 2, 5, 30, tzinfo=timezone.utc)
        with patch.object(reminders, "_utc_now", return_value=now):
            item = reminders.create_reminder(title="カフェへ行く", delay_minutes=30)

        self.assertEqual(item["status"], "scheduled")
        self.assertEqual(item["trigger_at"], "2026-08-02T06:00:00+00:00")
        data = reminders.list_reminders(scope="upcoming")
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["items"][0]["title"], "カフェへ行く")

    def test_naive_iso_time_uses_tokyo_timezone(self) -> None:
        now = datetime(2026, 8, 2, 0, 0, tzinfo=timezone.utc)
        with patch.object(reminders, "_utc_now", return_value=now):
            item = reminders.create_reminder(
                title="提出",
                trigger_at="2026-08-03T14:00:00",
            )
        self.assertEqual(item["trigger_at"], "2026-08-03T05:00:00+00:00")

    def test_due_reminder_dispatches_once_and_becomes_fired(self) -> None:
        now = datetime(2026, 8, 2, 5, 30, tzinfo=timezone.utc)
        with patch.object(reminders, "_utc_now", return_value=now):
            item = reminders.create_reminder(title="起きる", delay_minutes=1)

        due = now + timedelta(minutes=2)
        delivery = {"event_id": 77, "status": "sent", "sent": 1, "failed": 0, "disabled": 0}
        with patch.object(reminders.notifications, "dispatch_notification", return_value=delivery) as dispatch:
            first = reminders.process_due_reminders(now=due)
            second = reminders.process_due_reminders(now=due)

        self.assertEqual(first["processed"], 1)
        self.assertEqual(second["processed"], 0)
        dispatch.assert_called_once()
        self.assertEqual(dispatch.call_args.kwargs["category"], "schedule_reminder")
        fired = reminders.get_reminder(item["id"])
        self.assertEqual(fired["status"], "fired")
        self.assertEqual(fired["delivery_event_id"], 77)

    def test_disabled_push_still_records_fired_history(self) -> None:
        now = datetime(2026, 8, 2, 5, 30, tzinfo=timezone.utc)
        with patch.object(reminders, "_utc_now", return_value=now):
            item = reminders.create_reminder(title="通知設定確認", delay_minutes=1)

        result = {"event_id": 8, "status": "skipped_disabled", "sent": 0, "failed": 0, "disabled": 0}
        with patch.object(reminders.notifications, "dispatch_notification", return_value=result):
            reminders.process_due_reminders(now=now + timedelta(minutes=2))

        fired = reminders.get_reminder(item["id"])
        self.assertEqual(fired["status"], "fired")
        self.assertEqual(fired["delivery_status"], "skipped_disabled")

    def test_snooze_complete_and_cancel(self) -> None:
        now = datetime(2026, 8, 2, 5, 30, tzinfo=timezone.utc)
        with patch.object(reminders, "_utc_now", return_value=now):
            first = reminders.create_reminder(title="A", delay_minutes=30)
            second = reminders.create_reminder(title="B", delay_minutes=30)
            snoozed = reminders.snooze_reminder(first["id"], 10)

        self.assertEqual(snoozed["reminder"]["status"], "snoozed")
        self.assertEqual(snoozed["reminder"]["snooze_count"], 1)
        self.assertEqual(reminders.complete_reminder(first["id"])["reminder"]["status"], "completed")
        self.assertEqual(reminders.cancel_reminder(second["id"])["reminder"]["status"], "cancelled")
        self.assertEqual(reminders.list_reminders(scope="history")["count"], 2)

    def test_routes_and_notification_status_are_installed(self) -> None:
        paths = {route.path for route in reminders.notifications.router.routes}
        self.assertIn("/api/notifications/reminders", paths)
        self.assertIn("/api/notifications/reminders/{reminder_id}/snooze", paths)
        with patch.object(reminders, "status_summary", return_value={"counts": {}}):
            with patch.object(reminders, "_ORIGINAL_NOTIFICATION_STATUS", return_value={"supported": True}):
                status = reminders.notifications.notification_status()
        self.assertIn("reminders", status)


if __name__ == "__main__":
    unittest.main()
