from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class UniverseRenderSchedulerTests(unittest.TestCase):
    def test_scheduler_coalesces_named_jobs_in_one_animation_frame(self) -> None:
        source = (FRONTEND / "universe-render-scheduler.js").read_text(encoding="utf-8")
        self.assertIn("const jobs = new Map()", source)
        self.assertIn("const pending = new Map()", source)
        self.assertIn("window.requestAnimationFrame(flush)", source)
        self.assertIn("reasons.add", source)
        self.assertIn("register", source)
        self.assertIn("requestAll", source)
        self.assertIn("PetitUniverseRenderScheduler", source)

    def test_scheduler_is_loaded_before_app_shell(self) -> None:
        source = (FRONTEND / "petit-version.js").read_text(encoding="utf-8")
        scheduler = source.index("/static/universe-render-scheduler.js")
        app_shell = source.index("/static/app_shell.js")
        self.assertGreater(scheduler, app_shell)
        self.assertIn("loadAppShell", source)
        self.assertIn("PetitUniverseRenderScheduler?.initialized", source)

    def test_univ_render_modules_register_named_jobs(self) -> None:
        modules = {
            "life-map.js": 'const RENDER_JOB = "life-map"',
            "univ-space.js": 'const RENDER_JOB = "univ-space"',
            "universe-next.js": 'const RENDER_JOB = "universe-next"',
        }
        for filename, marker in modules.items():
            with self.subTest(filename=filename):
                source = (FRONTEND / filename).read_text(encoding="utf-8")
                self.assertIn(marker, source)
                self.assertIn("PetitUniverseRenderScheduler.register", source)
                self.assertIn("PetitUniverseRenderScheduler", source)
                self.assertIn("petit:render-scheduler-ready", source)

    def test_old_local_render_queues_are_removed(self) -> None:
        life_map = (FRONTEND / "life-map.js").read_text(encoding="utf-8")
        univ_space = (FRONTEND / "univ-space.js").read_text(encoding="utf-8")
        universe_next = (FRONTEND / "universe-next.js").read_text(encoding="utf-8")
        self.assertNotIn("let scheduled = false", life_map)
        self.assertNotIn("decorateQueued", univ_space)
        self.assertNotIn("isDecoratingScheduled", universe_next)
        self.assertNotIn("const scheduleDecorate", universe_next)

    def test_connection_visuals_are_css_owned(self) -> None:
        renderer = (FRONTEND / "life-map.js").read_text(encoding="utf-8")
        foundation = (FRONTEND / "universe-3d-foundation.css").read_text(encoding="utf-8")
        life_css = (FRONTEND / "life-map.css").read_text(encoding="utf-8")
        self.assertIn("--connection-length", renderer)
        self.assertNotIn("boxShadow", renderer)
        self.assertNotIn("linear-gradient(90deg", renderer)
        self.assertIn(".univ-connection-layer", foundation)
        self.assertIn(".univ-connection-3d", foundation)
        self.assertIn("--univ-space-background", foundation)
        self.assertNotIn(".life-map__connection", life_css)


if __name__ == "__main__":
    unittest.main()
