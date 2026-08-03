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
        self.html = (FRONTEND / "universe.html").read_text(encoding="utf-8")

    def test_motion_layer_is_loaded_with_single_asset_version(self) -> None:
        self.assertIn('window.PETIT_ASSET_VERSION = "0.8.0"', self.version)
        self.assertIn('window.PETIT_VERSION = "v0.8.0"', self.version)
        self.assertIn('window.PETIT_ASSET_VERSION || "0.8.0"', self.chat_input)
        self.assertIn('window.PETIT_ASSET_VERSION || "0.8.0"', self.app_shell)
        self.assertIn('loadStylesheet("/static/petit-motion.css"', self.chat_input)
        self.assertIn('loadSharedModule("/static/petit-motion.js"', self.chat_input)
        self.assertNotIn('?v=0.6.0', self.html)
        self.assertNotIn('?v=0.7.0', self.html)
        self.assertGreaterEqual(self.html.count('?v=0.8.0'), 10)

    def test_shared_element_transition_is_cancelable_and_state_first(self) -> None:
        self.assertIn("const performTransition = async", self.motion_js)
        self.assertIn("cancelActiveTransition();", self.motion_js)
        self.assertIn("await activate();", self.motion_js)
        self.assertIn("getBoundingClientRect()", self.motion_js)
        self.assertIn("ghostData.ghost.animate", self.motion_js)
        self.assertIn("transitionId", self.motion_js)
        self.assertIn("cleanupActive", self.motion_js)

    def test_life_click_replay_portal_is_removed(self) -> None:
        self.assertNotIn("life-dive-portal", self.life_map)
        self.assertNotIn("replayClick", self.life_map)
        self.assertNotIn("transitionBusy", self.life_map)
        self.assertIn("petit-motion.js", self.life_map)
        self.assertIn("dataset.motionKey", self.life_map)
        self.assertNotIn("life-dive-portal", self.life_transition)

    def test_life_focus_tasks_share_motion_keys(self) -> None:
        self.assertIn("data-motion-key", self.motion_js)
        self.assertIn(".universe-task[data-task-id]", self.motion_js)
        self.assertIn(".space-node[data-task-id]", self.motion_js)
        self.assertIn("#task-table-body tr[data-task-id]", self.motion_js)
        self.assertIn("window.PetitUniverse.focusTask", self.motion_js)
        self.assertIn("transitionTaskToFocus", self.motion_js)

    def test_tab_indicator_and_mobile_surfaces_are_defined(self) -> None:
        self.assertIn(".petit-tab-indicator", self.motion_css)
        self.assertIn("--tab-indicator-x", self.motion_css)
        self.assertIn("grid-template-areas", self.motion_css)
        self.assertIn('[data-view-panel="chat"] .chat-panel', self.motion_css)
        self.assertIn(".task-table tbody tr.is-completing", self.motion_css)

    def test_reduced_motion_keeps_navigation_functional(self) -> None:
        self.assertIn('prefers-reduced-motion: reduce', self.motion_css)
        self.assertIn("reducedMotion.matches", self.motion_js)
        self.assertIn("replayTab(tab)", self.motion_js)
        self.assertIn(".petit-shared-ghost { display: none", self.motion_css)


if __name__ == "__main__":
    unittest.main()
