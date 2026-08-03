from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class MotionContinuityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.motion_js = (FRONTEND / "petit-motion.js").read_text(encoding="utf-8")
        self.motion_css = (FRONTEND / "petit-motion.css").read_text(encoding="utf-8")
        self.life_map = (FRONTEND / "life-map.js").read_text(encoding="utf-8")
        self.life_transition = (FRONTEND / "life-transition.css").read_text(encoding="utf-8")
        self.chat_input = (FRONTEND / "chat_input.js").read_text(encoding="utf-8")
        self.app_shell = (FRONTEND / "app_shell.js").read_text(encoding="utf-8")
        self.version = (FRONTEND / "petit-version.js").read_text(encoding="utf-8")

    def test_motion_layer_uses_v090_assets(self) -> None:
        self.assertIn('window.PETIT_ASSET_VERSION = "0.9.0"', self.version)
        self.assertIn('window.PETIT_VERSION = "v0.9.0"', self.version)
        self.assertIn('window.PETIT_ASSET_VERSION || "0.9.0"', self.chat_input)
        self.assertIn('window.PETIT_ASSET_VERSION || "0.9.0"', self.app_shell)
        self.assertIn('loadStylesheet("/static/petit-motion.css"', self.chat_input)
        self.assertIn('loadSharedModule("/static/petit-motion.js"', self.chat_input)

    def test_life_focus_has_no_shared_element_or_depth_transition(self) -> None:
        self.assertNotIn("petit-shared-ghost", self.motion_js)
        self.assertNotIn("performTransition", self.motion_js)
        self.assertNotIn("animateGhost", self.motion_js)
        self.assertNotIn("data-petit-transition-from", self.life_transition)
        self.assertNotIn("life-dive-portal", self.life_map)
        self.assertIn("short fade", self.life_transition)

    def test_view_change_is_an_ordinary_short_fade(self) -> None:
        self.assertIn("replayViewFade", self.motion_js)
        self.assertIn("petit-view-fade", self.motion_js)
        self.assertIn("@keyframes petitViewFade", self.motion_css)
        self.assertIn("translateY(5px)", self.motion_css)
        self.assertNotIn("blur(", self.motion_css)
        self.assertNotIn("translate3d(", self.motion_css.split("@keyframes petitViewFade", 1)[1])

    def test_tab_indicator_and_task_feedback_remain(self) -> None:
        self.assertIn(".petit-tab-indicator", self.motion_css)
        self.assertIn("--tab-indicator-x", self.motion_css)
        self.assertIn(".task-table tbody tr.is-completing", self.motion_css)
        self.assertIn("installTaskFeedback", self.motion_js)

    def test_navigation_does_not_intercept_normal_click_flow(self) -> None:
        self.assertNotIn("stopImmediatePropagation", self.motion_js)
        self.assertNotIn("preventDefault()", self.motion_js)
        self.assertIn("tab.click()", self.motion_js)
        self.assertIn("window.PetitUniverse.focusTask", self.motion_js)

    def test_reduced_motion_keeps_navigation_functional(self) -> None:
        self.assertIn("prefers-reduced-motion: reduce", self.motion_css)
        self.assertIn("reducedMotion.matches", self.motion_js)
        self.assertIn("animation: none !important", self.motion_css)


if __name__ == "__main__":
    unittest.main()
