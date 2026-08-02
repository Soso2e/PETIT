from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from backend import time_context


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
BACKEND = ROOT / "backend"


class CurrentTimeContextTests(unittest.TestCase):
    def test_prompt_uses_configured_timezone_and_absolute_date(self) -> None:
        instant = datetime(2026, 8, 2, 7, 16, tzinfo=timezone.utc)
        with patch.dict(os.environ, {"PETIT_TIMEZONE": "Asia/Tokyo"}):
            text = time_context.prompt_context(instant)

        self.assertIn("2026-08-02T16:16:00+09:00", text)
        self.assertIn("今日: 2026-08-02（日曜日）", text)
        self.assertIn("知識カットオフ", text)

    def test_invalid_timezone_falls_back_to_tokyo(self) -> None:
        instant = datetime(2026, 8, 2, 7, 16, tzinfo=timezone.utc)
        with patch.dict(os.environ, {"PETIT_TIMEZONE": "Invalid/Timezone"}):
            value = time_context.snapshot(instant)

        self.assertEqual(value["timezone"], "Asia/Tokyo")
        self.assertEqual(value["current_date"], "2026-08-02")

    def test_context_is_recomputed_for_each_call(self) -> None:
        first = datetime(2026, 8, 2, 14, 59, tzinfo=timezone.utc)
        second = datetime(2026, 8, 2, 15, 1, tzinfo=timezone.utc)
        with patch.dict(os.environ, {"PETIT_TIMEZONE": "Asia/Tokyo"}):
            first_date = time_context.snapshot(first)["current_date"]
            second_date = time_context.snapshot(second)["current_date"]

        self.assertEqual(first_date, "2026-08-02")
        self.assertEqual(second_date, "2026-08-03")


class RuntimePromptWiringTests(unittest.TestCase):
    def test_agent_and_router_inject_fresh_time_context(self) -> None:
        agent = (BACKEND / "agent.py").read_text(encoding="utf-8")
        router = (BACKEND / "capability_router.py").read_text(encoding="utf-8")
        self.assertIn("_refresh_runtime_time_context", agent)
        self.assertIn("time_context.with_current_context", agent)
        self.assertIn("time_context.with_current_context(_ROUTER_SYSTEM_PROMPT)", router)


class DesktopUniverseLayoutTests(unittest.TestCase):
    def test_laptop_width_layout_safety_rules_exist(self) -> None:
        css = (FRONTEND / "reminders.css").read_text(encoding="utf-8")
        self.assertIn("@media (max-width: 1180px) and (min-width: 641px)", css)
        self.assertIn(".universe-topbar", css)
        self.assertIn(".view-tabs", css)
        self.assertIn(".focus-layout,", css)
        self.assertIn(".chat-layout", css)
        self.assertIn("grid-template-columns: 1fr", css)

    def test_service_worker_cache_version_is_bumped(self) -> None:
        script = (FRONTEND / "service-worker.js").read_text(encoding="utf-8")
        self.assertIn('const CACHE_NAME = "petit-shell-v8";', script)


if __name__ == "__main__":
    unittest.main()
