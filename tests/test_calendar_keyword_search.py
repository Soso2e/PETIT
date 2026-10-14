"""Regression for TimeTree keyword lookup vs historical calendar cache."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import calendar_sync, config, db
from backend.tools import schedule


TIMETREE_ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:old-dance
DTSTART:20170313T140000
SUMMARY:ダンス練習
END:VEVENT
BEGIN:VEVENT
UID:capcom-mtg
DTSTART:20261021T110000
DTEND:20261021T120000
SUMMARY:カプコン MTG
DESCRIPTION:打ち合わせ
END:VEVENT
BEGIN:VEVENT
UID:capcom-en
DTSTART:20261022T100000
SUMMARY:CAPCOM 説明会
END:VEVENT
END:VCALENDAR
"""


class CalendarKeywordSearchTests(unittest.TestCase):
    def test_timetree_date_and_keyword_reads_find_mtg_without_old_events(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(config, "DB_PATH", Path(tmp) / "petit.sqlite3"),
            patch.object(config, "CALENDAR_ICS_FILES", []),
            patch.object(config, "CALENDAR_ICS_URLS", []),
            patch.object(calendar_sync.timetree, "configured", return_value=True),
            patch.object(calendar_sync.timetree, "fetch_ics", return_value=TIMETREE_ICS),
            patch.object(calendar_sync, "_last_sync_monotonic", None),
            patch.object(calendar_sync, "_last_result", None),
        ):
            db.init_db()
            synced = calendar_sync.sync()
            self.assertEqual(synced["synced"], 3)

            by_date = schedule.get_schedule(date="2026-10-21")
            self.assertEqual([event["title"] for event in by_date["events"]], ["カプコン MTG"])

            for keyword in ("カプコン", "CAPCOM", "capcom"):
                with self.subTest(keyword=keyword):
                    found = schedule.get_schedule(query=keyword)
                    titles = {event["title"] for event in found["events"]}
                    self.assertEqual(found["count"], 2)
                    self.assertEqual(titles, {"カプコン MTG", "CAPCOM 説明会"})
                    self.assertNotIn("ダンス練習", titles)

            combined = schedule.get_schedule(date="2026-10-21", query="CAPCOM")
            self.assertEqual([event["title"] for event in combined["events"]], ["カプコン MTG"])
            self.assertEqual(schedule.get_schedule(query="CAP%")["count"], 0)
            self.assertEqual(schedule.get_schedule(query="ダンス")["count"], 1)


if __name__ == "__main__":
    unittest.main()
