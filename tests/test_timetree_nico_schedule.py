from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import ambient, briefing, calendar_sync, config, db, request_context, service_sync, setup_store, situation, time_context, tools
from backend.tools import schedule


def _build_ics(target_date: str) -> str:
    ymd = target_date.replace("-", "")
    return f"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:ev-soso
DTSTART:{ymd}T100000
DTEND:{ymd}T110000
SUMMARY:そその打ち合わせ
CATEGORIES:soso
COLOR:#757575
END:VEVENT
BEGIN:VEVENT
UID:ev-work
DTSTART:{ymd}T130000
DTEND:{ymd}T140000
SUMMARY:にこの仕事
CATEGORIES:work
COLOR:#3949ab
END:VEVENT
BEGIN:VEVENT
UID:ev-myplan
DTSTART:{ymd}T180000
DTEND:{ymd}T190000
SUMMARY:にこの個人予定
CATEGORIES: my plan 
COLOR:#fb7f77
END:VEVENT
END:VCALENDAR
"""


class TimeTreeNicoScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        tmp_path = Path(self.tmp.name)
        self.patches = [
            patch.object(config, "DB_PATH", tmp_path / "app.db"),
            patch.object(config, "CALENDAR_ICS_FILES", []),
            patch.object(config, "CALENDAR_ICS_URLS", []),
            patch.object(config, "TIMETREE_EMAIL", ""),
            patch.object(config, "TIMETREE_PASSWORD", ""),
            patch.object(config, "TIMETREE_CALENDAR_CODE", ""),
            patch.object(config, "AMBIENT_CONTEXT", True),
            patch.object(config, "AMBIENT_MAX_CHARS", 1800),
            patch.object(config, "notion_configured", lambda: False),
            patch.dict(os.environ, {"PETIT_SETTINGS_DIR": str(tmp_path / "settings")}),
            patch.object(calendar_sync, "_last_sync_monotonic", None),
            patch.object(calendar_sync, "_last_result", None),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        setup_store._sessions.clear()
        db.init_db()
        tools.register_builtin_tools()

    def test_service_sync_persists_and_backfills_timetree_label_metadata(self) -> None:
        today = time_context.current_date().isoformat()
        ics = _build_ics(today)
        setup_store.update(
            {"completed": True, "calendar": "timetree", "connected": ["timetree"]},
            {"timetree_email": "a@example.com", "timetree_password": "secret", "timetree_calendar": "cal-1"},
        )
        with patch("backend.calendar_sources.timetree.fetch_ics", return_value=ics):
            result = service_sync.sync(manual=True)
        self.assertTrue(result["ok"])
        key = service_sync.source_key()
        with db.get_connection() as conn:
            meta = {
                row["external_id"]: row["label_name"]
                for row in conn.execute(
                    "SELECT external_id, label_name FROM calendar_event_metadata WHERE source_key=?",
                    (key,),
                ).fetchall()
            }
        self.assertEqual(meta, {"ev-soso": "soso", "ev-work": "work", "ev-myplan": "my plan"})

        # Simulate pre-upgrade state where version fingerprint exists but metadata rows are missing.
        with db.write_transaction() as conn:
            conn.execute("DELETE FROM calendar_event_metadata WHERE source_key=?", (key,))
        with patch("backend.calendar_sources.timetree.fetch_ics", return_value=ics):
            second = service_sync.sync(manual=True)
        self.assertTrue(second["ok"])
        with db.get_connection() as conn:
            restored = conn.execute(
                "SELECT COUNT(*) FROM calendar_event_metadata WHERE source_key=?",
                (key,),
            ).fetchone()[0]
        self.assertEqual(restored, 3)

    def test_get_schedule_ambient_situation_and_briefing_isolate_nico_events(self) -> None:
        today = time_context.current_date().isoformat()
        ics = _build_ics(today)
        setup_store.update(
            {"completed": True, "calendar": "timetree", "connected": ["timetree"]},
            {"timetree_email": "a@example.com", "timetree_password": "secret", "timetree_calendar": "cal-1"},
        )
        with patch("backend.calendar_sources.timetree.fetch_ics", return_value=ics):
            service_sync.sync(manual=True)

        with patch.object(service_sync, "sync", return_value={"ok": True, "skipped": True}):
            default_res = schedule.get_schedule(date=today)
            self.assertEqual(default_res["scope"], "self")
            self.assertEqual([e["title"] for e in default_res["events"]], ["そその打ち合わせ"])
            self.assertEqual(default_res["events"][0]["schedule_group"], "self")

            nico_res = schedule.get_schedule(date=today, scope="nico")
            self.assertEqual(nico_res["scope"], "nico")
            self.assertEqual([e["title"] for e in nico_res["events"]], ["にこの仕事", "にこの個人予定"])
            self.assertTrue(all(e["schedule_group"] == "nico" for e in nico_res["events"]))

            all_res = schedule.get_schedule(date=today, scope="all")
            self.assertEqual(all_res["scope"], "all")
            self.assertEqual(len(all_res["events"]), 3)
            groups = {e["title"]: e["schedule_group"] for e in all_res["events"]}
            self.assertEqual(groups, {"そその打ち合わせ": "self", "にこの仕事": "nico", "にこの個人予定": "nico"})

            invalid_res = schedule.get_schedule(date=today, scope="other")
            self.assertEqual(invalid_res["error"], "invalid_scope")

        with request_context.bind(request_id="req-1", session_id="thread-1", is_admin=True):
            built = ambient.build("thread-1")
        self.assertIn("そその打ち合わせ", built["text"])
        self.assertIn("にこの予定は別枠のため除外", built["text"])
        self.assertNotIn("にこの仕事", built["text"])
        self.assertNotIn("にこの個人予定", built["text"])

        with patch.object(calendar_sync, "sync_if_configured", return_value={"configured": True, "synced": 0, "cached": True}):
            sit_text = situation.build_context_block("今日の予定を教えて")
        self.assertIn("そその打ち合わせ", sit_text)
        self.assertNotIn("にこの仕事", sit_text)
        self.assertNotIn("にこの個人予定", sit_text)

        brief_events = briefing._events_for(today)
        self.assertEqual([e["title"] for e in brief_events], ["そその打ち合わせ"])


if __name__ == "__main__":
    unittest.main()
