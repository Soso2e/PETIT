from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class UnivSpaceTests(unittest.TestCase):
    def test_app_shell_has_three_primary_areas(self):
        source = (FRONTEND / "app_shell.js").read_text(encoding="utf-8")
        self.assertIn('{ view: "univ", target: "universe", label: "Univ" }', source)
        self.assertIn('{ view: "tasks", target: "tasks", label: "Tasks" }', source)
        self.assertIn('{ view: "chat", target: "chat", label: "PETIT" }', source)
        self.assertNotIn('label: "Home"', source)
        self.assertNotIn('label: "Focus"', source)
        self.assertIn('home: "univ"', source)
        self.assertIn('focus: "univ"', source)
        self.assertIn('new CustomEvent("petit:univ-open"', source)

    def test_univ_assets_are_loaded(self):
        source = (FRONTEND / "app_shell.js").read_text(encoding="utf-8")
        self.assertIn('/static/univ-space.css', source)
        self.assertIn('/static/univ-space.js', source)
        self.assertTrue((FRONTEND / "univ-space.css").exists())
        self.assertTrue((FRONTEND / "univ-space.js").exists())

    def test_univ_camera_and_front_hud_exist(self):
        source = (FRONTEND / "univ-space.js").read_text(encoding="utf-8")
        self.assertIn('className = "univ-viewport"', source)
        self.assertIn('className = "univ-hud"', source)
        self.assertIn('data-univ-action="focus"', source)
        self.assertIn('data-univ-action="manage"', source)
        self.assertIn('addEventListener("pointermove"', source)
        self.assertIn('addEventListener("wheel"', source)
        self.assertIn('is-univ-focus-target', source)
        self.assertIn('petit-univ-manage-open', source)

    def test_css_uses_3d_space_and_mobile_three_tab_nav(self):
        source = (FRONTEND / "univ-space.css").read_text(encoding="utf-8")
        self.assertIn('perspective: 1280px', source)
        self.assertIn('transform-style: preserve-3d', source)
        self.assertIn('translateZ(var(--univ-task-depth', source)
        self.assertIn('grid-template-columns: repeat(3, minmax(0, 1fr))', source)
        self.assertIn('.petit-univ-active #detail-panel', source)
        self.assertIn('@media (prefers-reduced-motion: reduce)', source)


if __name__ == "__main__":
    unittest.main()
