from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from backend import context_broker


class ContextBrokerTests(unittest.TestCase):
    def test_normalize_request_accepts_only_read_sources(self) -> None:
        request = context_broker.normalize_request(
            {
                "needs": [
                    {"source": "tasks", "priority": "High"},
                    {"source": "calendar", "scope": "tomorrow"},
                    {"source": "github"},
                ],
                "goal": "明日の負荷を判断",
            }
        )
        self.assertEqual([item["source"] for item in request["needs"]], ["tasks", "calendar"])

    def test_collect_normalizes_tasks_and_calendar(self) -> None:
        def dispatch(name: str, arguments: dict) -> str:
            if name == "get_tasks":
                return json.dumps(
                    {
                        "tasks": [
                            {"title": "卒研", "priority": "High", "due_date": "2026-09-07", "status": "Yet"},
                            {"title": "暇タスク", "priority": "Low", "status": "Yet"},
                        ],
                        "sync": {"status": "fresh"},
                    },
                    ensure_ascii=False,
                )
            if name == "get_schedule":
                return json.dumps(
                    {
                        "events": [{"title": "大学", "start_time": "2026-09-07T14:00:00"}],
                        "calendar_sync": {"status": "fresh"},
                    },
                    ensure_ascii=False,
                )
            raise AssertionError(name)

        with patch.object(context_broker.tools, "dispatch", side_effect=dispatch):
            packet = context_broker.collect(
                {
                    "needs": [
                        {"source": "tasks", "priority": "High"},
                        {"source": "calendar", "date": "2026-09-07"},
                    ],
                    "goal": "明日の負荷",
                }
            )

        self.assertFalse(packet["partial"])
        self.assertEqual(packet["sources"][0]["facts"][0]["title"], "卒研")
        self.assertEqual(packet["sources"][0]["count"], 1)
        self.assertEqual(packet["sources"][1]["facts"][0]["title"], "大学")

    def test_one_provider_failure_keeps_other_context(self) -> None:
        def dispatch(name: str, arguments: dict) -> str:
            if name == "get_tasks":
                raise RuntimeError("notion unavailable")
            return json.dumps({"events": [{"title": "大学", "start_time": "2026-09-07T14:00:00"}]}, ensure_ascii=False)

        with patch.object(context_broker.tools, "dispatch", side_effect=dispatch):
            packet = context_broker.collect(
                {"needs": [{"source": "tasks"}, {"source": "calendar"}], "goal": "確認"}
            )

        self.assertTrue(packet["partial"])
        calendar = next(item for item in packet["sources"] if item["source"] == "calendar")
        self.assertEqual(calendar["count"], 1)
        self.assertTrue(packet["errors"])


if __name__ == "__main__":
    unittest.main()
