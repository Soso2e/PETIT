from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class GalacticSpatialDesignTests(unittest.TestCase):
    def setUp(self) -> None:
        self.css = (FRONTEND / "petit-galaxy.css").read_text(encoding="utf-8")
        self.shell = (FRONTEND / "app_shell.js").read_text(encoding="utf-8")
        self.worker = (FRONTEND / "service-worker.js").read_text(encoding="utf-8")

    def test_galaxy_layer_is_loaded_last_and_precached(self) -> None:
        self.assertIn('loadStylesheet("/static/petit-galaxy.css", "galactic-spatial-style")', self.shell)
        self.assertLess(self.shell.index('loadStylesheet("/static/task-flow.css"'), self.shell.index('loadStylesheet("/static/petit-galaxy.css"'))
        self.assertIn('"/static/petit-galaxy.css"', self.worker)

    def test_life_uses_scalable_atlas_cards(self) -> None:
        self.assertIn("grid-template-columns: repeat(3, minmax(0, 1fr))", self.css)
        self.assertIn("position: relative !important", self.css)
        self.assertIn("left: auto !important", self.css)
        self.assertIn(".life-star-system .universe-task-list", self.css)
        self.assertIn(".life-star-system .life-task-star--overflow { display: grid !important; }", self.css)

    def test_focus_tasks_today_reminders_and_chat_share_layout_language(self) -> None:
        for selector in (
            ".focus-layout",
            ".task-table-wrap",
            ".today-card",
            ".reminder-list",
            ".chat-layout",
            ".detail-panel",
        ):
            self.assertIn(selector, self.css)
        self.assertIn("--galaxy-panel", self.css)
        self.assertIn("--galaxy-line", self.css)
        self.assertIn("--galaxy-radius-xl", self.css)

    def test_mobile_is_a_real_one_column_layout(self) -> None:
        self.assertIn("@media (max-width: 720px)", self.css)
        mobile = self.css.split("@media (max-width: 720px)", 1)[1]
        self.assertIn("grid-template-columns: minmax(0, 1fr)", mobile)
        self.assertIn("grid-template-columns: repeat(5, minmax(0, 1fr))", mobile)
        self.assertIn(".task-table thead { display: none; }", mobile)
        self.assertIn(".detail-panel", mobile)
        self.assertIn("position: relative", mobile)
        self.assertIn("@media (max-width: 390px)", self.css)

    def test_light_and_reduced_motion_are_supported(self) -> None:
        self.assertIn('html[data-theme="light"]', self.css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.css)
        self.assertIn("animation: none !important", self.css)


if __name__ == "__main__":
    unittest.main()
