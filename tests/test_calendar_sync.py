from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import calendar_sync, config, db


ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:one
DTSTART:20260712T100000Z
DTEND:20260712T110000Z
SUMMARY:Portfolio review
LOCATION:Online
DESCRIPTION:Bring notes
END:VEVENT
BEGIN:VEVENT
UID:two
DTSTART;VALUE=DATE:20260713
SUMMARY:All day task
END:VEVENT
END:VCALENDAR
"""

TIMETREE_ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:timetree-one
DTSTART:20260712T100000Z
DTEND:20260712T110000Z
SUMMARY:授業
CATEGORIES:そそ
COLOR:#4F86F7
X-TIMETREE-LABEL-ID:label-123
END:VEVENT
BEGIN:VEVENT
UID:timetree-two
DTSTART:20260713T120000Z
SUMMARY:ラベルなし予定
END:VEVENT
END:VCALENDAR
"""


class CalendarSyncTests(unittest.TestCase):
    def test_parse_ics_events(self) -> None:
        events = calendar_sync.parse_ics(ICS)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["title"], "Portfolio review")
        self.assertEqual(events[0]["start_time"], "2026-07-12T10:00:00+00:00")
        self.assertEqual(events[1]["start_time"], "2026-07-13")
        self.assertIsNone(events[0]["label_name"])
        self.assertIsNone(events[0]["label_color"])
        self.assertIsNone(events[0]["label_id"])

    def test_parse_timetree_label_metadata(self) -> None:
        events = calendar_sync.parse_ics(TIMETREE_ICS)
        self.assertEqual(events[0]["label_name"], "そそ")
        self.assertEqual(events[0]["label_color"], "#4F86F7")
        self.assertEqual(events[0]["label_id"], "label-123")
        self.assertIsNone(events[1]["label_name"])

    def test_sync_local_ics_file_into_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "petit.sqlite3"
            ics_path = tmp_path / "calendar.ics"
            ics_path.write_text(ICS, encoding="utf-8")

            with (
                patch.object(config, "DB_PATH", db_path),
                patch.object(config, "CALENDAR_ICS_FILES", [ics_path]),
                patch.object(config, "CALENDAR_ICS_URLS", []),
                patch.object(calendar_sync.timetree, "configured", return_value=False),
            ):
                db.init_db()
                result = calendar_sync.sync()
                conn = db.get_connection()
                try:
                    rows = conn.execute(
                        "SELECT source, title, start_time FROM calendar_events_cache ORDER BY start_time"
                    ).fetchall()
                finally:
                    conn.close()

            self.assertEqual(result["synced"], 2)
            self.assertEqual([row["source"] for row in rows], ["ics_file", "ics_file"])
            self.assertEqual(rows[0]["title"], "Portfolio review")

    def test_timetree_sync_persists_label_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "petit.sqlite3"
            with (
                patch.object(config, "DB_PATH", db_path),
                patch.object(config, "CALENDAR_ICS_FILES", []),
                patch.object(config, "CALENDAR_ICS_URLS", []),
                patch.object(calendar_sync.timetree, "configured", return_value=True),
                patch.object(calendar_sync.timetree, "fetch_ics", return_value=TIMETREE_ICS),
            ):
                db.init_db()
                result = calendar_sync.sync()
                conn = db.get_connection()
                try:
                    metadata = conn.execute(
                        "SELECT external_id, label_name, label_color, label_id "
                        "FROM calendar_event_metadata ORDER BY external_id"
                    ).fetchall()
                finally:
                    conn.close()

            self.assertEqual(result["synced"], 2)
            self.assertEqual(len(metadata), 1)
            self.assertEqual(metadata[0]["external_id"], "timetree-one")
            self.assertEqual(metadata[0]["label_name"], "そそ")
            self.assertEqual(metadata[0]["label_color"], "#4F86F7")
            self.assertEqual(metadata[0]["label_id"], "label-123")


if __name__ == "__main__":
    unittest.main()
