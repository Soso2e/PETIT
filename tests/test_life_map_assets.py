from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class LifeMapAssetTests(unittest.TestCase):
    def test_app_shell_loads_life_map_assets(self):
        source = (FRONTEND / "app_shell.js").read_text(encoding="utf-8")

        self.assertIn('loadStylesheet("/static/life-map.css", "life-map-style")', source)
        self.assertIn('loadScript("/static/life-map.js", "life-map-script")', source)
        self.assertIn('data-view-panel="universe"', source)

    def test_life_map_uses_existing_project_and_task_focus_hooks(self):
        source = (FRONTEND / "life-map.js").read_text(encoding="utf-8")

        self.assertIn('const MAP_SELECTOR = "#constellation-grid"', source)
        self.assertIn('classList?.contains("constellation-card")', source)
        self.assertIn('querySelector(".constellation-card__header")', source)
        self.assertIn('querySelectorAll(":scope > .universe-task")', source)
        self.assertIn("MutationObserver", source)
        self.assertIn("life-map__connection", source)
        self.assertIn("へフォーカス", source)

    def test_life_map_has_mobile_and_reduced_motion_styles(self):
        source = (FRONTEND / "life-map.css").read_text(encoding="utf-8")

        self.assertIn(".constellation-grid.life-cosmos-map", source)
        self.assertIn(".life-map__connection.is-active", source)
        self.assertIn(".life-star-system .universe-task.life-task-star", source)
        self.assertIn("@media (max-width: 640px)", source)
        self.assertIn("@media (prefers-reduced-motion: reduce)", source)


if __name__ == "__main__":
    unittest.main()
