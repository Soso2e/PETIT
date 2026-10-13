from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from backend import config, work_sessions


class WorkDayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(config, "DB_PATH", Path(self.temp.name) / "work.db")
        self.db_patch.start()
        app = FastAPI()
        app.include_router(work_sessions.router)
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.db_patch.stop()
        self.temp.cleanup()

    def test_past_day_clips_midnight_and_pauses_using_actual_now(self):
        # 23:30 JST -> 01:30 JST, with a pause spanning midnight.
        start = datetime(2026, 10, 10, 14, 30, tzinfo=timezone.utc)
        work_sessions.start_session("cross-day", "制作", now=start)
        work_sessions.pause_session("cross-day", now=start + timedelta(minutes=20))
        work_sessions.resume_session("cross-day", now=start + timedelta(minutes=60))
        work_sessions.end_session("cross-day", now=start + timedelta(hours=2))
        now = start + timedelta(days=2)
        previous = work_sessions.day_summary(date(2026, 10, 10), now=now)
        following = work_sessions.day_summary(date(2026, 10, 11), now=now)
        self.assertEqual(previous["total_seconds"], 20 * 60)
        self.assertEqual(following["total_seconds"], 60 * 60)
        self.assertIsNone(previous["active"])

    def test_reflection_persists_separately_per_day_and_cannot_overwrite(self):
        first, second = date(2026, 10, 10), date(2026, 10, 11)
        self.assertEqual(work_sessions.reflection_for_day(first)["revision"], 0)
        result = work_sessions.save_reflection(first, work_sessions.WorkDayReflection(note="  一歩進んだ\n次は仕上げ  ", revision=0))
        self.assertEqual(result["note"], "一歩進んだ\n次は仕上げ")
        self.assertEqual(result["revision"], 1)
        with self.assertRaises(HTTPException) as raised:
            work_sessions.save_reflection(first, work_sessions.WorkDayReflection(note="古いタブ", revision=0))
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(work_sessions.reflection_for_day(first), result)
        self.assertEqual(work_sessions.reflection_for_day(second)["note"], "")
        work_sessions.save_reflection(first, work_sessions.WorkDayReflection(note="", revision=1))
        self.assertEqual(work_sessions.reflection_for_day(first)["note"], "")

    def test_api_calendar_validation_and_revision_conflict(self):
        fixed = datetime(2026, 10, 13, 0, tzinfo=timezone.utc)
        with patch.object(work_sessions, "_now", return_value=fixed):
            self.assertEqual(self.client.get("/api/work-sessions/days/2026-02-30").status_code, 422)
            self.assertEqual(self.client.get("/api/work-sessions/days/2026-10-14").status_code, 422)
            path = "/api/work-sessions/days/2026-10-12"
            day = self.client.get(path).json()
            self.assertEqual(day["date"], "2026-10-12")
            self.assertEqual(day["total_seconds"], 0)
            self.assertEqual(self.client.put(path + "/reflection", json={"note": "x" * 2001, "revision": 0}).status_code, 422)
            self.assertEqual(self.client.put(path + "/reflection", json={"note": "できた", "revision": 0}).status_code, 200)
            self.assertEqual(self.client.put(path + "/reflection", json={"note": "競合", "revision": 0}).status_code, 409)
            self.assertEqual(self.client.get(path).json()["reflection"]["note"], "できた")
            self.assertIn("reflection", self.client.get("/api/work-sessions/today").json())


if __name__ == "__main__":
    unittest.main()
