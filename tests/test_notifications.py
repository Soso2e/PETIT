from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import config, db, notifications


class FakeProvider:
    name = "fake"

    def __init__(self, error: notifications.NotificationDeliveryError | None = None) -> None:
        self.error = error
        self.payloads: list[dict] = []

    def send(self, subscription: dict, payload: dict) -> None:
        if self.error:
            raise self.error
        self.payloads.append({"subscription": subscription, "payload": payload})


class NotificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(config, "DB_PATH", Path(self.temp_dir.name) / "app.db")
        self.db_patch.start()
        db.init_db()
        notifications.init_db()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def subscription(self, endpoint: str = "https://push.example.test/subscription") -> notifications.BrowserSubscription:
        return notifications.BrowserSubscription(
            endpoint=endpoint,
            keys={"p256dh": "public-key", "auth": "auth-secret"},
        )

    def test_preferences_are_opt_in_and_persisted(self) -> None:
        preferences = notifications.get_preferences()
        self.assertEqual(set(preferences), set(notifications.CATEGORY_LABELS))
        self.assertFalse(any(preferences.values()))

        updated = notifications.update_preferences({"morning_briefing": True})
        self.assertTrue(updated["morning_briefing"])
        self.assertFalse(updated["high_task"])

    def test_subscription_can_be_registered_and_disabled(self) -> None:
        saved = notifications.upsert_subscription(self.subscription(), user_agent="test-browser")
        self.assertEqual(saved["provider"], "web_push")
        self.assertEqual(len(notifications.active_subscriptions()), 1)

        self.assertTrue(notifications.disable_subscription(saved["endpoint"]))
        self.assertEqual(notifications.active_subscriptions(), [])
        self.assertFalse(notifications.disable_subscription(saved["endpoint"]))

    def test_disabled_category_is_audited_without_delivery(self) -> None:
        provider = FakeProvider()
        result = notifications.dispatch_notification(
            category="high_task",
            title="Highタスク",
            body="締切が近いタスクがあります。",
            provider=provider,
        )

        self.assertEqual(result["status"], "skipped_disabled")
        self.assertEqual(provider.payloads, [])
        with db.get_connection() as conn:
            delivery = conn.execute(
                "SELECT status FROM notification_deliveries WHERE event_id=?",
                (result["event_id"],),
            ).fetchone()
        self.assertEqual(delivery["status"], "skipped_disabled")

    def test_enabled_category_is_sent_through_provider_boundary(self) -> None:
        notifications.update_preferences({"work_session": True})
        notifications.upsert_subscription(self.subscription())
        provider = FakeProvider()

        result = notifications.dispatch_notification(
            category="work_session",
            title="そろそろ区切る？",
            body="作業を始めて20分経ったよ。",
            url="/?mode=work",
            provider=provider,
        )

        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["sent"], 1)
        payload = provider.payloads[0]["payload"]
        self.assertEqual(payload["category"], "work_session")
        self.assertEqual(payload["event_id"], result["event_id"])
        self.assertIn("mode=work", payload["url"])
        self.assertIn(f"notification={result['event_id']}", payload["url"])

    def test_permanent_delivery_error_disables_stale_subscription(self) -> None:
        notifications.update_preferences({"github_ci_failure": True})
        notifications.upsert_subscription(self.subscription())
        provider = FakeProvider(
            notifications.NotificationDeliveryError("subscription is gone", permanent=True)
        )

        result = notifications.dispatch_notification(
            category="github_ci_failure",
            title="CI失敗",
            body="PETITのCIが失敗しました。",
            provider=provider,
        )

        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["disabled"], 1)
        self.assertEqual(notifications.active_subscriptions(), [])


if __name__ == "__main__":
    unittest.main()
