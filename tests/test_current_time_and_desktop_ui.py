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
    def test_router_injects_context_user_side_and_keeps_agent_prefix_static(self) -> None:
        agent = (BACKEND / "agent.py").read_text(encoding="utf-8")
        router = (BACKEND / "capability_router.py").read_text(encoding="utf-8")
        self.assertIn("_refresh_runtime_time_context", agent)
        self.assertIn("_RUNTIME_AGENT_BASE_PROMPT", agent)
        self.assertNotIn("time_context.with_current_context", agent)
        self.assertIn("time_context.prompt_context_for", router)
        self.assertIn('f"{text}\\n\\n{runtime_context}"', router)


class ResponsiveUniverseLayoutTests(unittest.TestCase):
    @staticmethod
    def _responsive_css() -> str:
        return "\n".join(
            (FRONTEND / name).read_text(encoding="utf-8")
            for name in ("petit-ui-system.css", "petit-motion.css", "petit-galaxy.css")
        )

    def test_laptop_layout_stacks_focus_and_chat_before_phone_width(self) -> None:
        css = self._responsive_css()
        self.assertIn("@media (max-width:1040px)", css)
        self.assertIn(".focus-layout,.chat-layout { grid-template-columns:1fr; }", css)
        self.assertIn(".detail-panel,.chat-context { position:static; max-height:none; }", css)
        self.assertIn("@media (max-width: 1180px)", css)

    def test_mobile_navigation_fits_primary_tabs_inside_viewport(self) -> None:
        css = self._responsive_css()
        self.assertIn("@media (max-width: 720px)", css)
        self.assertIn("grid-template-columns: repeat(5, minmax(0, 1fr))", css)
        self.assertIn(".petit-tab-indicator", css)
        self.assertIn("overflow: visible", css)

    def test_mobile_content_panels_use_compact_spacing_and_cards(self) -> None:
        css = self._responsive_css()
        self.assertIn("padding: 18px 16px 0;", css)
        self.assertIn(".detail-panel { padding:16px; }", css)
        self.assertIn("grid-template-areas:", css)
        self.assertIn(".chat-composer", css)
        self.assertIn("bottom: calc(72px + env(safe-area-inset-bottom))", css)


if __name__ == "__main__":
    unittest.main()
