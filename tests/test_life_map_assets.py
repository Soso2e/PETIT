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

    def test_life_map_uses_current_task_system_and_scheduler_hooks(self):
        source = (FRONTEND / "life-map.js").read_text(encoding="utf-8")

        self.assertIn('const MAP_SELECTOR = "#constellation-grid"', source)
        self.assertIn('classList?.contains("univ-task-system")', source)
        self.assertIn('querySelector(".universe-task-list")', source)
        self.assertIn('querySelectorAll(":scope > .univ-satellite")', source)
        self.assertIn("PetitUniverseRenderScheduler", source)
        self.assertIn("univ-connection-layer", source)
        self.assertIn("add3dConnection", source)
        self.assertIn("depthBand", source)

    def test_life_map_has_mobile_reduced_motion_and_shared_3d_styles(self):
        fallback = (FRONTEND / "life-map.css").read_text(encoding="utf-8")
        foundation = (FRONTEND / "universe-3d-foundation.css").read_text(encoding="utf-8")

        self.assertIn(".constellation-grid.life-cosmos-map", fallback)
        self.assertIn("@media (max-width: 640px)", fallback)
        self.assertIn("@media (prefers-reduced-motion: reduce)", fallback)
        self.assertIn(".univ-connection-layer", foundation)
        self.assertIn(".univ-connection-3d.is-active", foundation)
        self.assertIn(".univ-connection-3d.is-child", foundation)
        self.assertIn("@media (prefers-reduced-motion: reduce)", foundation)


if __name__ == "__main__":
    unittest.main()
