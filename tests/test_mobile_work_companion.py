from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class MobileWorkCompanionStaticTests(unittest.TestCase):
    def test_index_loads_session_before_chat_and_companion_after_voice(self) -> None:
        html = (FRONTEND / "index.html").read_text(encoding="utf-8")
        self.assertLess(html.index('/static/session.js'), html.index('/static/app.js'))
        self.assertLess(html.index('/static/voice.js'), html.index('/static/companion.js'))
        for element_id in (
            "work-task",
            "work-toggle",
            "work-frequency",
            "work-elapsed",
            "history-toggle",
            "dashboard-tasks",
            "dashboard-schedule",
        ):
            self.assertIn(f'id="{element_id}"', html)

    def test_manifest_is_valid_and_standalone(self) -> None:
        manifest = json.loads((FRONTEND / "manifest.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["start_url"], "/static/index.html?source=pwa")
        self.assertEqual(manifest["scope"], "/static/")
        self.assertTrue(manifest["icons"])

    def test_session_split_and_internal_prompt_filter_are_present(self) -> None:
        source = (FRONTEND / "session.js").read_text(encoding="utf-8")
        self.assertIn("2 * 60 * 60 * 1000", source)
        self.assertIn("[PETIT_INTERNAL_EVENT]", source)
        self.assertIn('/api/conversations', source)

    def test_companion_is_foreground_only_and_keeps_three_rallies(self) -> None:
        source = (FRONTEND / "companion.js").read_text(encoding="utf-8")
        self.assertIn("const MAX_VISIBLE_MESSAGES = 6", source)
        self.assertIn('document.visibilityState === "visible"', source)
        self.assertIn("10 * 60 * 1000", source)
        self.assertIn("Highタスク", source)
        self.assertIn("作業モードを終了したよ", source)

    def test_service_worker_never_caches_api_requests(self) -> None:
        source = (FRONTEND / "sw.js").read_text(encoding="utf-8")
        self.assertIn('url.pathname.startsWith("/api/")', source)
        self.assertIn("fetch(request)", source)


if __name__ == "__main__":
    unittest.main()
