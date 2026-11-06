from __future__ import annotations

import json
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from backend.lmstudio_client import LMStudioError
from backend.tools import registry
from backend.tools.builtins import register_builtin_tools


class ScheduleDateParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.today = date(2026, 7, 21)





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





    def test_registry_dispatch_preserves_schedule_date_argument(self) -> None:
        register_builtin_tools()
        target = {"date": "2026-07-13"}
        tool_obj = registry._REGISTRY["get_schedule"]
        with patch.object(tool_obj, "handler", return_value={"date": target["date"], "events": []}) as handler:
            result = registry.dispatch("get_schedule", target)
        handler.assert_called_once_with(date="2026-07-13")
        self.assertEqual(json.loads(result)["date"], "2026-07-13")


if __name__ == "__main__":
    unittest.main()
