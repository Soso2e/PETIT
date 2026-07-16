from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from unittest.mock import Mock

from sona_agent_core import MemoryAuditSink

from backend import calendar_sync, config, db, sona_core_schedule
from backend.tools import registry, schedule


class SonaCoreScheduleTests(unittest.TestCase):
    def test_feature_flag_disabled_uses_legacy_handler(self) -> None:
        tool = registry._REGISTRY["get_schedule"]
        with (
            patch.object(config, "USE_SONA_CORE", False),
            patch.object(tool, "handler", return_value={"count": 1, "events": []}) as legacy,
        ):
            self.assertEqual(json.loads(registry.dispatch("get_schedule", {"date": "2026-07-17"}))["count"], 1)
        legacy.assert_called_once_with(date="2026-07-17")

    def test_feature_flag_enabled_uses_core_dispatch(self) -> None:
        with (
            patch.object(config, "USE_SONA_CORE", True),
            patch.object(sona_core_schedule, "dispatch_get_schedule", return_value='{"count": 2, "events": []}') as core_dispatch,
        ):
            self.assertEqual(json.loads(registry.dispatch("get_schedule", {"date": "2026-07-17"}))["count"], 2)
        core_dispatch.assert_called_once_with({"date": "2026-07-17"})

    def test_core_result_keeps_legacy_schedule_data_and_emits_audit(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(config, "DB_PATH", Path(tmp) / "petit.db"),
            patch.object(calendar_sync.timetree, "configured", return_value=False),
        ):
            db.init_db()
            with db.get_connection() as conn:
                conn.execute(
                    "INSERT INTO calendar_events_cache (source, title, start_time, updated_at) VALUES (?, ?, ?, ?)",
                    ("local", "Core integration", "2026-07-17T10:00:00+09:00", db.now_iso()),
                )
            legacy = schedule.get_schedule("2026-07-17")
            audit = MemoryAuditSink()
            result = asyncio.run(sona_core_schedule.execute_get_schedule({"date": "2026-07-17"}, audit_sink=audit))

        self.assertEqual(result.status, "success")
        self.assertEqual({key: result.data[key] for key in ("date", "count", "events")}, {key: legacy[key] for key in ("date", "count", "events")})
        self.assertEqual(result.freshness.status, "unknown")
        self.assertEqual(result.sources[0].provider, "local")
        self.assertEqual(len(audit.events), 1)
        self.assertEqual(audit.events[0].tool_name, "get_schedule")
        self.assertEqual(audit.events[0].context.metadata["execution_path"], "sona_core")
        self.assertEqual(
            audit.events[0].metadata["sources"],
            [{"provider": "local", "resource_type": "calendar_events_cache", "external_id": "local"}],
        )
        self.assertEqual(audit.events[0].metadata["freshness"]["status"], "unknown")
        self.assertIsNotNone(audit.events[0].metadata["freshness"]["observed_at"])
        self.assertFalse(audit.events[0].metadata["stale"])

    def test_scope_and_capability_are_enforced(self) -> None:
        adapter = sona_core_schedule.PetitGetScheduleAdapter(lambda **_: {"count": 0, "events": [], "calendar_sync": {"ok": True}})
        missing_capability = sona_core_schedule.build_context(capabilities=())
        denied = asyncio.run(sona_core_schedule.execute_get_schedule({}, context=missing_capability, adapter=adapter))
        self.assertEqual(denied.status, "denied")
        self.assertEqual(denied.error.code, "CAPABILITY_INSUFFICIENT")

    def test_personal_scope_succeeds(self) -> None:
        handler = Mock(return_value={"count": 0, "events": [], "calendar_sync": {"ok": True}})
        result = asyncio.run(
            sona_core_schedule.execute_get_schedule(
                {}, context=sona_core_schedule.build_context(scope_id="soso"), adapter=sona_core_schedule.PetitGetScheduleAdapter(handler)
            )
        )
        self.assertEqual(result.status, "success")
        handler.assert_called_once_with(date=None)

    def test_fresh_source_and_freshness_are_recorded_in_audit(self) -> None:
        schedule_data = {
            "count": 1,
            "events": [{"source": "google_ics", "title": "Current"}],
            "calendar_sync": {"ok": True, "stale": False, "last_synced_at": "2026-07-17T01:00:00+00:00", "error": None},
        }
        audit = MemoryAuditSink()
        result = asyncio.run(
            sona_core_schedule.execute_get_schedule(
                {}, adapter=sona_core_schedule.PetitGetScheduleAdapter(lambda **_: schedule_data), audit_sink=audit
            )
        )
        event = audit.events[0]
        self.assertEqual(result.status, "success")
        self.assertEqual(event.status, "success")
        self.assertEqual(event.metadata["sources"][0]["provider"], "google_ics")
        self.assertEqual(event.metadata["freshness"]["status"], "fresh")
        self.assertEqual(event.metadata["freshness"]["source_updated_at"], "2026-07-17T01:00:00+00:00")
        self.assertIsNotNone(event.metadata["freshness"]["observed_at"])
        self.assertFalse(event.metadata["stale"])
        self.assertEqual(event.metadata["last_synced_at"], "2026-07-17T01:00:00+00:00")
        self.assertIsNone(event.metadata["sync_error"])

    def test_non_personal_primary_scope_is_denied_without_calling_handler(self) -> None:
        handler = Mock(return_value={"count": 0, "events": [], "calendar_sync": {"ok": True}})
        context = sona_core_schedule.build_context()
        context = context.model_copy(
            update={"scopes": context.scopes.model_copy(update={"primary": context.scopes.primary.model_copy(update={"type": "project", "id": "petit"})})}
        )
        result = asyncio.run(
            sona_core_schedule.execute_get_schedule({}, context=context, adapter=sona_core_schedule.PetitGetScheduleAdapter(handler))
        )
        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error.code, "SCOPE_NOT_SUPPORTED")
        handler.assert_not_called()

    def test_stale_cache_is_explicit_in_result_and_audit_context(self) -> None:
        stale_schedule = {
            "date": "2026-07-17",
            "count": 1,
            "events": [{"source": "google_ics", "title": "Cached", "start_time": "2026-07-17T10:00:00+09:00"}],
            "calendar_sync": {"ok": False, "stale": True, "last_synced_at": "2026-07-16T10:00:00+00:00", "error": "sync failed"},
        }
        audit = MemoryAuditSink()
        result = asyncio.run(
            sona_core_schedule.execute_get_schedule(
                {"date": "2026-07-17"},
                adapter=sona_core_schedule.PetitGetScheduleAdapter(lambda **_: stale_schedule),
                audit_sink=audit,
            )
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(result.freshness.status, "stale")
        self.assertTrue(result.sources[0].metadata["stale"])
        self.assertEqual(audit.events[0].status, "success")
        self.assertEqual(
            audit.events[0].metadata["sources"],
            [{"provider": "google_ics", "resource_type": "calendar_events_cache", "external_id": "google_ics"}],
        )
        self.assertEqual(audit.events[0].metadata["freshness"]["status"], "stale")
        self.assertEqual(audit.events[0].metadata["freshness"]["source_updated_at"], "2026-07-16T10:00:00+00:00")
        self.assertTrue(audit.events[0].metadata["stale"])
        self.assertEqual(audit.events[0].metadata["last_synced_at"], "2026-07-16T10:00:00+00:00")
        self.assertEqual(audit.events[0].metadata["sync_error"], "sync failed")

    def test_core_unavailable_does_not_fall_back_to_legacy_handler(self) -> None:
        with (
            patch.object(sona_core_schedule, "execute_get_schedule", side_effect=ImportError("missing")),
            patch.object(schedule, "get_schedule") as legacy,
        ):
            result = sona_core_schedule.dispatch_get_schedule({"date": "2026-07-17"})
        self.assertTrue(result.startswith("[error] Sona Agent Core is unavailable"))
        legacy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
