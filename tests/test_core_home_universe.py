from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class CoreHomeUniverseTests(unittest.TestCase):
    def test_app_shell_uses_universe_as_home(self):
        source = (FRONTEND / "app_shell.js").read_text(encoding="utf-8")
        self.assertIn('const HOME_VIEW = "universe"', source)
        self.assertIn('{ view: "home", target: "universe", label: "Home" }', source)
        self.assertIn('{ view: "focus", target: "universe", label: "Focus" }', source)
        self.assertIn('window.dispatchEvent(new CustomEvent("petit:core-focus"))', source)
        self.assertIn('window.dispatchEvent(new CustomEvent("petit:core-home"))', source)

    def test_core_home_assets_are_loaded(self):
        source = (FRONTEND / "app_shell.js").read_text(encoding="utf-8")
        self.assertIn('/static/core-home.css', source)
        self.assertIn('/static/core-home.js', source)
        self.assertTrue((FRONTEND / "core-home.css").exists())
        self.assertTrue((FRONTEND / "core-home.js").exists())

    def test_core_copy_and_focus_states_exist(self):
        source = (FRONTEND / "core-home.js").read_text(encoding="utf-8")
        self.assertIn('coreTitle.textContent = "CORE"', source)
        self.assertIn('graph.classList.toggle("is-core-focus"', source)
        self.assertIn('is-core-focus-target', source)
        self.assertIn('is-core-focus-family', source)
        self.assertIn('event.key !== "Escape"', source)

    def test_reduced_motion_is_supported(self):
        source = (FRONTEND / "core-home.css").read_text(encoding="utf-8")
        self.assertIn('@media (prefers-reduced-motion: reduce)', source)
        self.assertIn('.is-core-focus-target', source)


if __name__ == "__main__":
    unittest.main()
