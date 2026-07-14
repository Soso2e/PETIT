from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import calendar_sync, config, db
from backend.tools import notion

ICS = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:one
DTSTART:20260714T100000Z
SUMMARY:予定
END:VEVENT
END:VCALENDAR
"""


class ExternalSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "test.db"
        self.patches = [patch.object(config, "DB_PATH", self.db), patch.object(config, "CALENDAR_ICS_URLS", []), patch.object(config, "CALENDAR_ICS_FILES", [])]
        for item in self.patches: item.start()
        db.init_db()

    def tearDown(self):
        for item in reversed(self.patches): item.stop()
        self.tmp.cleanup()

    def event_count(self, source_key):
        with db.get_connection() as conn:
            return conn.execute("SELECT COUNT(*) FROM calendar_events_cache WHERE source_key=?", (source_key,)).fetchone()[0]

    def test_calendar_success_and_restart_state(self):
        with patch.object(config, "CALENDAR_ICS_URLS", ["https://private.example/secret"]), patch.object(calendar_sync, "_read_url", return_value=ICS):
            result = calendar_sync.sync()
        self.assertTrue(result["ok"])
        self.assertEqual(result["synced_count"], 1)
        self.assertTrue(db.sync_state("google_ics:1")["last_success_at"])
        self.assertEqual(self.event_count("google_ics:1"), 1)

    def test_calendar_failure_preserves_existing_cache_and_hides_url(self):
        calendar_sync._replace_source("google_ics:1", "google_ics", calendar_sync.parse_ics(ICS))
        db.record_sync_success("google_ics:1", 1)
        with patch.object(config, "CALENDAR_ICS_URLS", ["https://private.example/token"]), patch.object(calendar_sync, "_read_url", side_effect=OSError("https://private.example/token")):
            result = calendar_sync.sync()
        self.assertFalse(result["ok"])
        self.assertTrue(result["sources"][0]["stale"])
        self.assertNotIn("token", result["sources"][0]["error"])
        self.assertEqual(self.event_count("google_ics:1"), 1)

    def test_partial_calendar_failure_keeps_only_failed_source_cache(self):
        calendar_sync._replace_source("local_ics:1", "local_ics", calendar_sync.parse_ics(ICS))
        db.record_sync_success("local_ics:1", 1)
        missing = Path(self.tmp.name) / "missing.ics"
        with patch.object(config, "CALENDAR_ICS_URLS", ["ok"]), patch.object(config, "CALENDAR_ICS_FILES", [missing]), patch.object(calendar_sync, "_read_url", return_value=ICS):
            result = calendar_sync.sync()
        self.assertTrue(result["ok"])
        self.assertEqual(self.event_count("google_ics:1"), 1)
        self.assertEqual(self.event_count("local_ics:1"), 1)

    def test_timetree_result_is_persisted(self):
        with patch.object(calendar_sync.timetree, "configured", return_value=True), patch.object(calendar_sync.timetree, "fetch_ics", return_value=ICS):
            result = calendar_sync.sync()
        self.assertEqual(result["sources"][0]["source"], "timetree")
        self.assertTrue(db.sync_state("timetree")["last_success_at"])

    def test_notion_success_failure_and_unconfigured(self):
        task = {"external_id": "p1", "title": "task", "status": "Yet", "due_date": None, "priority": "Mid"}
        with patch.object(config, "notion_configured", return_value=False):
            self.assertFalse(notion.sync_if_configured()["ok"])
        with patch.object(config, "notion_configured", return_value=True), patch.object(notion, "query_database", return_value=[task]):
            result = notion.sync_if_configured(force=True)
        self.assertTrue(result["ok"])
        with patch.object(config, "notion_configured", return_value=True), patch.object(notion, "query_database", side_effect=notion.NotionError("bad " + config.NOTION_API_KEY)):
            failed = notion.sync_if_configured(force=True)
        self.assertFalse(failed["ok"])
        self.assertTrue(failed["stale"])
        self.assertTrue(failed["cached"])
        with db.get_connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM tasks_cache WHERE source='notion'").fetchone()[0], 1)


if __name__ == "__main__": unittest.main()
