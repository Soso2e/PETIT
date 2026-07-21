from __future__ import annotations

import json
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from backend import agent, config
from backend.date_parser import has_schedule_date_expression, parse_schedule_date
from backend.lmstudio_client import LMStudioError
from backend.tools import registry


class ScheduleDateParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.today = date(2026, 7, 21)

    def test_relative_dates(self) -> None:
        self.assertEqual(parse_schedule_date("今日の予定", today=self.today), self.today)
        self.assertEqual(parse_schedule_date("明日の予定", today=self.today), self.today + timedelta(days=1))
        self.assertEqual(parse_schedule_date("昨日の予定", today=self.today), self.today - timedelta(days=1))

    def test_explicit_date_formats(self) -> None:
        self.assertEqual(parse_schedule_date("2026-07-13の予定", today=self.today), date(2026, 7, 13))
        self.assertEqual(parse_schedule_date("2026年7月13日の予定", today=self.today), date(2026, 7, 13))
        self.assertEqual(parse_schedule_date("7月13日の予定", today=self.today), date(2026, 7, 13))

    def test_invalid_and_ambiguous_dates_are_not_resolved(self) -> None:
        self.assertIsNone(parse_schedule_date("2026-02-30の予定", today=self.today))
        self.assertIsNone(parse_schedule_date("来週月曜の予定", today=self.today))
        self.assertTrue(has_schedule_date_expression("2026-02-30の予定"))
        self.assertTrue(has_schedule_date_expression("来週月曜の予定"))


class ForcedScheduleReadTests(unittest.TestCase):
    @staticmethod
    def _schedule_result(target: str, *, events: list[dict[str, str]] | None = None) -> str:
        return json.dumps(
            {
                "date": target,
                "count": len(events or []),
                "events": events or [],
                "calendar_sync": {"stale": False},
            },
            ensure_ascii=False,
        )

    def test_resolved_date_is_passed_to_schedule_tool(self) -> None:
        captured: list[tuple[str, dict[str, str]]] = []

        def fake_dispatch(name: str, arguments: dict[str, str]) -> str:
            captured.append((name, arguments))
            return self._schedule_result(arguments["date"])

        with (
            patch.object(agent.tools, "dispatch", side_effect=fake_dispatch),
            patch.object(agent, "_complete", return_value=({"content": "予定を確認しました"}, "agent", None)),
        ):
            result = agent._run_forced_read("2026年7月13日の予定を教えて", [], "get_schedule")

        self.assertEqual(captured, [("get_schedule", {"date": "2026-07-13"})])
        self.assertEqual(json.loads(result["used_tools"][0]["arguments"])["date"], "2026-07-13")

    def test_today_and_tomorrow_keep_existing_behavior(self) -> None:
        captured: list[str] = []

        def fake_dispatch(name: str, arguments: dict[str, str]) -> str:
            captured.append(arguments["date"])
            return self._schedule_result(arguments["date"])

        with (
            patch.object(agent.tools, "dispatch", side_effect=fake_dispatch),
            patch.object(agent, "_complete", return_value=({"content": "確認しました"}, "agent", None)),
        ):
            agent._run_forced_read("今日の予定を教えて", [], "get_schedule")
            agent._run_forced_read("明日の予定を教えて", [], "get_schedule")

        self.assertEqual(captured[0], date.today().isoformat())
        self.assertEqual(captured[1], (date.today() + timedelta(days=1)).isoformat())

    def test_invalid_or_ambiguous_date_requests_confirmation_without_dispatch(self) -> None:
        for message in ("2026-02-30の予定を教えて", "来週月曜の予定を教えて"):
            with self.subTest(message=message), patch.object(agent.tools, "dispatch") as dispatch:
                result = agent._run_forced_read(message, [], "get_schedule")
            dispatch.assert_not_called()
            self.assertEqual(result["model_route"]["fallback_reason"], "invalid_or_ambiguous_schedule_date")
            self.assertFalse(result["persist"])

    def test_models_unavailable_returns_deterministic_schedule_reply(self) -> None:
        content = self._schedule_result(
            "2026-07-13",
            events=[{"title": "打ち合わせ", "start_time": "2026-07-13T15:00:00"}],
        )
        with (
            patch.object(agent.tools, "dispatch", return_value=content),
            patch.object(agent, "_complete", side_effect=LMStudioError("offline")),
        ):
            result = agent._run_forced_read("2026-07-13の予定を教えて", [], "get_schedule")

        self.assertIn("2026-07-13の予定は1件", result["reply"])
        self.assertIn("打ち合わせ", result["reply"])
        self.assertEqual(result["model_route"]["actual_route"], "deterministic")

    def test_legacy_and_sona_core_receive_the_same_date_argument(self) -> None:
        target = {"date": "2026-07-13"}
        tool_obj = registry._REGISTRY["get_schedule"]

        with (
            patch.object(config, "USE_SONA_CORE", False),
            patch.object(tool_obj, "handler", return_value={"date": target["date"], "events": []}) as legacy,
        ):
            registry.dispatch("get_schedule", target)
        legacy.assert_called_once_with(date="2026-07-13")

        with (
            patch.object(config, "USE_SONA_CORE", True),
            patch("backend.sona_core_schedule.dispatch_get_schedule", return_value="{}") as core,
        ):
            registry.dispatch("get_schedule", target)
        core.assert_called_once_with(target)


if __name__ == "__main__":
    unittest.main()
