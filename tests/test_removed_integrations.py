"""Regression coverage for removal of optional Sona and Linkraft integrations."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from backend import config, pending_actions, tools
from backend.chat_models import ActionDecision
from backend.tools import registry


class RemovedIntegrationsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        tools.register_builtin_tools()

    def tearDown(self) -> None:
        with pending_actions._pending_actions_lock:
            pending_actions._pending_actions.clear()

    def test_sona_and_linkraft_are_not_registered_or_required(self) -> None:
        names = set(tools.registered_names())
        self.assertNotIn("sync_linkraft_projects", names)
        self.assertNotIn("get_linkraft_project_candidates", names)
        self.assertNotIn("link_linkraft_project_candidate", names)
        self.assertFalse(hasattr(config, "USE_SONA_CORE"))
        self.assertIn("get_schedule", names)
        self.assertIn("add_schedule", names)

    def test_schedule_read_uses_registered_handler(self) -> None:
        tool = registry._REGISTRY["get_schedule"]
        expected = {"count": 1, "events": [{"title": "meeting"}]}
        with patch.object(tool, "handler", return_value=expected) as handler:
            result = json.loads(registry.dispatch("get_schedule", {"date": "2026-10-29"}))
        handler.assert_called_once_with(date="2026-10-29")
        self.assertEqual(result, expected)

    def test_schedule_write_stays_confirmation_gated(self) -> None:
        self.assertTrue(tools.requires_confirmation("add_schedule"))
        payload = {"name": "add_schedule", "arguments": {
            "title": "meeting", "start_time": "2026-10-30T10:00:00+09:00"}}
        registered = pending_actions.register([payload])
        self.assertEqual(len(registered), 1)
        with patch("backend.conversation_api.decide", return_value=None), patch.object(
            pending_actions.tools, "dispatch", return_value='{"added": true}'
        ) as dispatch:
            response = pending_actions.decide_action(
                registered[0].approval_id, ActionDecision(approved=True))
        dispatch.assert_called_once_with("add_schedule", payload["arguments"])
        self.assertIsNone(response.error)
        self.assertEqual(response.used_tools[0]["name"], "add_schedule")

    def test_rejected_schedule_does_not_write(self) -> None:
        registered = pending_actions.register([{"name": "add_schedule", "arguments": {
            "title": "meeting", "start_time": "2026-10-30T10:00:00+09:00"}}])
        with patch("backend.conversation_api.decide", return_value=None), patch.object(
            pending_actions.tools, "dispatch"
        ) as dispatch:
            response = pending_actions.decide_action(
                registered[0].approval_id, ActionDecision(approved=False))
        dispatch.assert_not_called()
        self.assertIn("キャンセル", response.reply)


if __name__ == "__main__":
    unittest.main()
