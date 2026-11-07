from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class MobileChromeTests(unittest.TestCase):
    """Chat / Univ / Develop / Dashboard share one phone header and tab bar."""

    def setUp(self):
        self.chrome = (FRONTEND / "petit-mobile-chrome.css").read_text(encoding="utf-8")
        self.polish = (FRONTEND / "petit-ui-polish.css").read_text(encoding="utf-8")
        self.tidy = (FRONTEND / "chat-tidy.js").read_text(encoding="utf-8")

    def test_chrome_stylesheet_loads_after_polish(self):
        corner = (FRONTEND / "petit-corner-shell.js").read_text(encoding="utf-8")
        polish_at = corner.index('"petit-ui-polish.css"')
        chrome_at = corner.index('"petit-mobile-chrome.css"')
        self.assertLess(polish_at, chrome_at)

    def test_chat_does_not_move_the_utility_dock(self):
        # The old Chat-only override placed bell/settings below the work bar.
        self.assertNotRegex(
            self.polish,
            r"body\.petit-chat-screen \.petit-utility-dock \{\s*top: calc\(var\(--petit-work-top\) \+ 52px\)",
        )
        # The chrome gives Chat and every other area the same dock position.
        self.assertIn("html body .petit-utility-dock,\n  html body.petit-chat-screen .petit-utility-dock {", self.chrome)

    def test_chat_panel_stays_between_header_and_tab_bar(self):
        self.assertIn("--petit-tabbar-h: calc(58px + env(safe-area-inset-bottom))", self.chrome)
        self.assertRegex(
            self.chrome,
            r'body\.petit-chat-screen \[data-view-panel="chat"\] \{\s*position: fixed;\s*inset: var\(--petit-header-h\) 0 var\(--petit-tabbar-h\) 0;',
        )

    def test_composer_input_is_16px_to_avoid_ios_zoom(self):
        self.assertRegex(self.chrome, r"textarea#chat-input \{ font-size: 16px; \}")

    def test_work_session_bar_is_folded_into_header(self):
        self.assertIn('#petit-context-bar[data-state="idle"] > summary { width: 40px;', self.chrome)
        self.assertIn("top: calc(var(--petit-chrome-top) + 8px);", self.chrome)

    def test_chat_tidy_only_reparents_existing_controls(self):
        self.assertIn(".petit-thread-controls", self.tidy)
        self.assertIn(".chat-voice-settings", self.tidy)
        self.assertIn('aria-label", "画像を添付"', self.tidy)
        self.assertIn('submit.setAttribute("aria-label", "送信")', self.tidy)
        # Pending turn results must remain discoverable while the menu is closed.
        self.assertIn('textContent.includes("再取得")', self.tidy)
        self.assertNotIn("fetch(", self.tidy)

    def test_assets_are_loaded_and_cached(self):
        html = (FRONTEND / "universe.html").read_text(encoding="utf-8")
        worker = (FRONTEND / "service-worker.js").read_text(encoding="utf-8")
        self.assertIn('"/static/chat-tidy.js"', html)
        self.assertIn('"/static/chat-tidy.js"', worker)
        self.assertIn('"/static/petit-mobile-chrome.css"', worker)
        self.assertRegex(worker, r"mobilechrome\d+")

    def test_version_files_agree(self):
        version = (FRONTEND / "petit-version.js").read_text(encoding="utf-8")
        shown = re.search(r'PETIT_VERSION = "v(\d+\.\d+\.\d+)"', version).group(1)
        release = (FRONTEND / "version.json").read_text(encoding="utf-8")
        self.assertIn(f'"version": "{shown}"', release)
        self.assertEqual((ROOT / "VERSION").read_text(encoding="utf-8").strip(), shown)


if __name__ == "__main__":
    unittest.main()
