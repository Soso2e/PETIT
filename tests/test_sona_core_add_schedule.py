from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from sona_agent_core import MemoryAuditSink

from backend import calendar_sync, config, db, main, sona_core_add_schedule, sona_core_schedule
from backend.tools import schedule


ARGS = {
    "title": "Sona Core Milestone 3確認",
    "start_time": "2026-07-20T14:00:00+09:00",
    "end_time": "2026-07-20T15:00:00+09:00",
    "location": "オンライン",
    "description": "進捗確認",
    "destination": "local",
}


class SonaCoreAddScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "petit.db"
        self.audit_path = Path(self.tmp.name) / "audit.jsonl"
        self.patches = [
            patch.object(config, "DB_PATH", self.db_path),
            patch.object(config, "SONA_CORE_AUDIT_PATH", self.audit_path),
            patch.object(calendar_sync.timetree, "configured", return_value=False),
        ]
        for item in self.patches:
            item.start()
        db.init_db()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def count(self) -> int:
        with db.get_connection() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM calendar_events_cache WHERE source='local'").fetchone()[0])

    def test_approval_precedes_write_and_original_invocation_runs_once(self) -> None:
        audit = MemoryAuditSink()
        approval_id, pending = asyncio.run(sona_core_add_schedule.create_approval(ARGS, audit_sink=audit))
        self.assertEqual(pending.status, "pending_approval")
        self.assertEqual(self.count(), 0)
        result = asyncio.run(sona_core_add_schedule.decide(approval_id, True, audit_sink=audit))
        self.assertEqual(result.status, "success")
        self.assertEqual(self.count(), 1)
        self.assertEqual(schedule.get_schedule("2026-07-20")["events"][0]["title"], ARGS["title"])
        with self.assertRaises(ValueError):
            asyncio.run(sona_core_add_schedule.decide(approval_id, True, audit_sink=audit))
        self.assertEqual(self.count(), 1)
        event_types = [event.event_type for event in audit.events]
        self.assertIn("approval.requested", event_types)
        self.assertIn("approval.approved", event_types)
        self.assertIn("tool.started", event_types)
        self.assertIn("tool.completed", event_types)
        completed = next(event for event in audit.events if event.event_type == "tool.completed")
        self.assertEqual(completed.after["id"], result.data["id"])
        self.assertEqual(completed.metadata["created_schedule_id"], result.data["id"])
        self.assertTrue(completed.metadata["feature_flag"])

    def test_rejection_does_not_write_and_is_audited(self) -> None:
        audit = MemoryAuditSink()
        approval_id, _ = asyncio.run(sona_core_add_schedule.create_approval(ARGS, audit_sink=audit))
        self.assertIsNone(asyncio.run(sona_core_add_schedule.decide(approval_id, False, audit_sink=audit)))
        self.assertEqual(self.count(), 0)
        self.assertIn("approval.rejected", [event.event_type for event in audit.events])

    def test_expired_approval_cannot_execute(self) -> None:
        audit = MemoryAuditSink()
        with patch.object(config, "SONA_CORE_APPROVAL_TTL_SECONDS", -1):
            approval_id, _ = asyncio.run(sona_core_add_schedule.create_approval(ARGS, audit_sink=audit))
            with self.assertRaises(ValueError):
                asyncio.run(sona_core_add_schedule.decide(approval_id, True, audit_sink=audit))
        self.assertEqual(self.count(), 0)
        self.assertIn("approval.expired", [event.event_type for event in audit.events])

    def test_capability_scope_and_destination_are_enforced(self) -> None:
        missing = sona_core_schedule.build_context(capabilities=())
        _, denied = asyncio.run(sona_core_add_schedule.create_approval(ARGS, context=missing, audit_sink=MemoryAuditSink()))
        self.assertEqual(denied.error.code, "CAPABILITY_INSUFFICIENT")
        project = sona_core_schedule.build_context(capabilities=("schedule.write",)).model_copy(
            update={"scopes": missing.scopes.model_copy(update={"primary": missing.scopes.primary.model_copy(update={"type": "project"})})}
        )
        _, denied = asyncio.run(sona_core_add_schedule.create_approval(ARGS, context=project, audit_sink=MemoryAuditSink()))
        self.assertEqual(denied.error.code, "SCOPE_NOT_SUPPORTED")
        _, result = asyncio.run(sona_core_add_schedule.create_approval({**ARGS, "destination": "google_calendar"}, audit_sink=MemoryAuditSink()))
        self.assertEqual(result.status, "denied")
        self.assertEqual(result.error.code, "DESTINATION_NOT_SUPPORTED")
        self.assertEqual(self.count(), 0)

    def test_same_idempotency_key_hits_persistent_result_and_conflicts_on_different_arguments(self) -> None:
        audit = MemoryAuditSink()
        key = "stable-key"
        first_id, _ = asyncio.run(sona_core_add_schedule.create_approval(ARGS, audit_sink=audit, idempotency_key=key))
        first = asyncio.run(sona_core_add_schedule.decide(first_id, True, audit_sink=audit))
        second_id, _ = asyncio.run(sona_core_add_schedule.create_approval(ARGS, audit_sink=audit, idempotency_key=key))
        second = asyncio.run(sona_core_add_schedule.decide(second_id, True, audit_sink=audit))
        self.assertEqual(second.data["id"], first.data["id"])
        self.assertEqual(self.count(), 1)
        self.assertIn("tool.idempotency_hit", [event.event_type for event in audit.events])
        third_id, _ = asyncio.run(sona_core_add_schedule.create_approval({**ARGS, "title": "different"}, audit_sink=audit, idempotency_key=key))
        conflict = asyncio.run(sona_core_add_schedule.decide(third_id, True, audit_sink=audit))
        self.assertEqual(conflict.status, "conflict")
        self.assertEqual(conflict.error.code, "IDEMPOTENCY_CONFLICT")
        self.assertEqual(self.count(), 1)

    def test_write_failure_is_not_reported_as_success(self) -> None:
        writer = Mock(return_value={"added": False, "error": "disk full"})
        adapter = sona_core_add_schedule.PetitAddScheduleAdapter(writer)
        approval_id, _ = asyncio.run(sona_core_add_schedule.create_approval(ARGS, adapter=adapter, audit_sink=MemoryAuditSink()))
        result = asyncio.run(sona_core_add_schedule.decide(approval_id, True, adapter=adapter, audit_sink=MemoryAuditSink()))
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error.message, "disk full")
        writer.assert_called_once_with(**ARGS)

    def test_main_feature_flag_switches_between_core_and_legacy_approval(self) -> None:
        with patch.object(config, "USE_SONA_CORE", False):
            pending = main._register_pending_actions([{"name": "add_schedule", "arguments": ARGS}])[0]
            self.assertNotIn("petit-approval-", pending.approval_id)
            with main._pending_actions_lock:
                self.assertIn(pending.approval_id, main._pending_actions)
                main._pending_actions.pop(pending.approval_id, None)
        with patch.object(config, "USE_SONA_CORE", True):
            pending = main._register_pending_actions([{"name": "add_schedule", "arguments": ARGS}])[0]
            self.assertTrue(pending.approval_id.startswith("petit-approval-"))
            response = main.decide_action(pending.approval_id, main.ActionDecision(approved=True))
            self.assertIsNone(response.error)
        self.assertEqual(self.count(), 1)


if __name__ == "__main__":
    unittest.main()
