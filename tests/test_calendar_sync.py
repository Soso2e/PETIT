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


class CalendarSyncTests(unittest.TestCase):
    def test_parse_ics_events(self) -> None:
        events = calendar_sync.parse_ics(ICS)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["title"], "Portfolio review")
        self.assertEqual(events[0]["start_time"], "2026-07-12T10:00:00+00:00")
        self.assertEqual(events[1]["start_time"], "2026-07-13")

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


if __name__ == "__main__":
    unittest.main()
