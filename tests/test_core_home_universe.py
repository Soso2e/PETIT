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
        self.assertIn("switchPanelDirectly(panelView)", source)

    def test_univ_assets_are_loaded(self):
        source = (FRONTEND / "app_shell.js").read_text(encoding="utf-8")
        self.assertIn('/static/univ-space.css', source)
        self.assertIn('/static/univ-space.js', source)
        self.assertTrue((FRONTEND / "univ-space.css").exists())
        self.assertTrue((FRONTEND / "univ-space.js").exists())

    def test_univ_camera_hud_and_in_space_focus_exist(self):
        source = (FRONTEND / "univ-space.js").read_text(encoding="utf-8")
        self.assertIn('className = "univ-viewport"', source)
        self.assertIn('className = "univ-hud"', source)
        self.assertIn('data-univ-selected-description', source)
        self.assertIn('data-univ-action="focus"', source)
        self.assertIn('data-univ-action="manage"', source)
        self.assertIn('addEventListener("pointermove"', source)
        self.assertIn('addEventListener("wheel"', source)
        self.assertIn('is-univ-focus-target', source)
        self.assertIn('petit-univ-manage-open', source)
        self.assertIn('event.stopImmediatePropagation()', source)
        self.assertNotIn('switchView("focus")', source)

    def test_planet_semantics_are_explicit(self):
        source = (FRONTEND / "univ-space.js").read_text(encoding="utf-8")
        self.assertIn('univ-core-planet', source)
        self.assertIn('univ-task-planet', source)
        self.assertIn('univ-satellite', source)
        self.assertIn('univ-root-task-copy', source)
        self.assertIn('CENTER PLANET', source)
        self.assertIn('親タスク惑星', source)
        self.assertIn('子タスク衛星', source)

    def test_css_uses_lightweight_3d_spheres_and_mobile_three_tab_nav(self):
        source = (FRONTEND / "univ-space.css").read_text(encoding="utf-8")
        self.assertIn('perspective: 1400px', source)
        self.assertIn('transform-style: preserve-3d', source)
        self.assertIn('translateZ(var(--satellite-depth))', source)
        self.assertIn('.univ-core-planet', source)
        self.assertIn('.univ-task-planet', source)
        self.assertIn('.univ-satellite', source)
        self.assertIn('grid-template-columns: repeat(3, minmax(0, 1fr))', source)
        self.assertIn('.petit-univ-active #detail-panel', source)
        self.assertIn('@media (prefers-reduced-motion: reduce)', source)


if __name__ == "__main__":
    unittest.main()
