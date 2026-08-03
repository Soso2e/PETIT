from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class ThreeAreaAppShellTests(unittest.TestCase):
    def test_app_shell_defines_three_primary_areas(self):
        source = (FRONTEND / "app_shell.js").read_text(encoding="utf-8")
        for label in ('label: "Univ"', 'label: "Tasks"', 'label: "PETIT"'):
            self.assertIn(label, source)
        self.assertNotIn('label: "Home"', source)
        self.assertNotIn('label: "Focus"', source)
        self.assertNotIn('textContent = "More"', source)
        self.assertNotIn('legacy.html?view=', source)

    def test_mobile_navigation_is_overridden_to_three_columns(self):
        source = (FRONTEND / "univ-space.css").read_text(encoding="utf-8")
        self.assertIn("grid-template-columns: repeat(3, minmax(0, 1fr))", source)
        shell = (FRONTEND / "petit-four-area-shell.css").read_text(encoding="utf-8")
        self.assertIn("env(safe-area-inset-bottom)", shell)
        self.assertIn("min-height: 48px", shell)

    def test_desktop_uses_left_area_rail(self):
        source = (FRONTEND / "petit-four-area-shell.css").read_text(encoding="utf-8")
        self.assertIn(".petit-area-rail", source)
        self.assertIn("padding-left: var(--petit-rail-width)", source)

    def test_univ_assets_are_versioned_and_loaded(self):
        shell = (FRONTEND / "app_shell.js").read_text(encoding="utf-8")
        self.assertIn('window.PETIT_ASSET_VERSION || "0.12.0"', shell)
        self.assertIn('/static/univ-space.css', shell)
        self.assertIn('/static/univ-space.js', shell)

    def test_version_is_v0120(self):
        source = (FRONTEND / "petit-version.js").read_text(encoding="utf-8")
        self.assertIn('window.PETIT_VERSION = "v0.12.0"', source)


if __name__ == "__main__":
    unittest.main()
