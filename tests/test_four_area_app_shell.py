from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class FourAreaAppShellTests(unittest.TestCase):
    def test_app_shell_defines_four_primary_areas(self):
        source = (FRONTEND / "app_shell.js").read_text(encoding="utf-8")
        for label in ('label: "Home"', 'label: "Focus"', 'label: "Tasks"', 'label: "PETIT"'):
            self.assertIn(label, source)
        self.assertNotIn('textContent = "More"', source)
        self.assertNotIn('legacy.html?view=', source)

    def test_mobile_navigation_is_four_columns(self):
        source = (FRONTEND / "petit-four-area-shell.css").read_text(encoding="utf-8")
        self.assertIn("grid-template-columns: repeat(4, minmax(0, 1fr))", source)
        self.assertIn("env(safe-area-inset-bottom)", source)
        self.assertIn("min-height: 48px", source)

    def test_desktop_uses_left_area_rail(self):
        source = (FRONTEND / "petit-four-area-shell.css").read_text(encoding="utf-8")
        self.assertIn(".petit-area-rail", source)
        self.assertIn("padding-left: var(--petit-rail-width)", source)

    def test_pwa_cache_contains_new_shell_asset(self):
        source = (FRONTEND / "service-worker.js").read_text(encoding="utf-8")
        self.assertIn('petit-shell-v0.10.0', source)
        self.assertIn('/static/petit-four-area-shell.css', source)

    def test_version_is_v0100(self):
        source = (FRONTEND / "petit-version.js").read_text(encoding="utf-8")
        self.assertIn('window.PETIT_VERSION = "v0.10.0"', source)


if __name__ == "__main__":
    unittest.main()
