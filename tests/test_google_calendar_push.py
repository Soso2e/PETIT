from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from backend import google_calendar_push


EVENT = {
    "external_id": "tt-123",
    "title": "大学",
    "start_time": "2026-09-12T10:00:00+09:00",
    "end_time": "2026-09-12T11:00:00+09:00",
    "location": "新宿",
    "description": "中間発表",
    "label_name": "そそ",
    "label_color": "#4F86F7",
    "label_id": "label-123",
}


class GoogleCalendarPushTests(unittest.TestCase):
    def test_disabled_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(google_calendar_push.enabled())
            self.assertEqual(
                google_calendar_push.sync_events([EVENT]),
                {"created": 0, "updated": 0, "skipped": 1},
            )

    def test_body_contains_readable_label_and_private_metadata(self) -> None:
        body = google_calendar_push._body(EVENT)
        self.assertIn("TimeTreeラベル: そそ", body["description"])
        private = body["extendedProperties"]["private"]
        self.assertEqual(private["petit_source"], "timetree")
        self.assertEqual(private["petit_timetree_uid"], "tt-123")
        self.assertEqual(private["timetree_label"], "そそ")
        self.assertEqual(private["timetree_label_id"], "label-123")

    def test_existing_uid_is_patched_not_inserted(self) -> None:
        service = MagicMock()
        service.events.return_value.list.return_value.execute.return_value = {"items": [{"id": "google-1"}]}
        service.events.return_value.patch.return_value.execute.return_value = {"id": "google-1"}
        with (
            patch.dict(os.environ, {"PETIT_GOOGLE_CALENDAR_SYNC_ENABLED": "1"}, clear=True),
            patch.object(google_calendar_push, "_service", return_value=service),
        ):
            result = google_calendar_push.sync_events([EVENT])
        self.assertEqual(result, {"created": 0, "updated": 1, "skipped": 0})
        service.events.return_value.patch.assert_called_once()
        service.events.return_value.insert.assert_not_called()

    def test_new_uid_is_inserted(self) -> None:
        service = MagicMock()
        service.events.return_value.list.return_value.execute.return_value = {"items": []}
        service.events.return_value.insert.return_value.execute.return_value = {"id": "google-2"}
        with (
            patch.dict(os.environ, {"PETIT_GOOGLE_CALENDAR_SYNC_ENABLED": "1"}, clear=True),
            patch.object(google_calendar_push, "_service", return_value=service),
        ):
            result = google_calendar_push.sync_events([EVENT])
        self.assertEqual(result, {"created": 1, "updated": 0, "skipped": 0})
        service.events.return_value.insert.assert_called_once()


if __name__ == "__main__":
    unittest.main()
