from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class MobileCompanionAcceptanceTests(unittest.TestCase):
    """Regression contract for the user-visible requirements in Issue #80."""

    @classmethod
    def setUpClass(cls):
        cls.index = (FRONTEND / "index.html").read_text(encoding="utf-8")
        cls.companion = (FRONTEND / "companion.js").read_text(encoding="utf-8")
        cls.session = (FRONTEND / "session.js").read_text(encoding="utf-8")
        cls.voice = (FRONTEND / "voice.js").read_text(encoding="utf-8")
        cls.manifest = (FRONTEND / "manifest.webmanifest").read_text(encoding="utf-8")
        cls.service_worker = (FRONTEND / "sw.js").read_text(encoding="utf-8")

    def test_mobile_dashboard_controls_are_present(self):
        for element_id in (
            "companion-dashboard",
            "work-task",
            "work-toggle",
            "work-pause",
            "work-end",
            "work-check-now",
            "work-frequency",
            "dashboard-next",
            "dashboard-schedule",
            "dashboard-tasks",
        ):
            self.assertIn(f'id="{element_id}"', self.index)

    def test_work_state_is_persisted_and_restored(self):
        self.assertIn('const STORAGE_KEY = "petit_work_companion_v1"', self.companion)
        self.assertIn("localStorage.getItem(STORAGE_KEY)", self.companion)
        self.assertIn("localStorage.setItem(STORAGE_KEY", self.companion)
        self.assertIn("renderWorkState();", self.companion)

    def test_proactive_check_ins_only_run_in_foreground(self):
        self.assertIn('document.visibilityState !== "visible"', self.companion)
        self.assertIn('document.addEventListener("visibilitychange"', self.companion)
        self.assertRegex(self.companion, r"setInterval\([^)]*tick|setInterval\(tick")

    def test_internal_events_never_render_as_user_messages(self):
        self.assertIn('[PETIT_INTERNAL_EVENT]', self.session)
        self.assertIn('next.user_text = ""', self.session)
        self.assertIn("internalPrefix()", self.companion)
        self.assertIn("history: []", self.companion)

    def test_conversation_window_defaults_to_three_rallies(self):
        self.assertIn("const MAX_VISIBLE_MESSAGES = 6", self.companion)
        self.assertIn("msg--history-hidden", self.companion)
        self.assertIn("直近3ラリー", self.companion)

    def test_idle_session_split_is_two_hours(self):
        self.assertIn("const IDLE_SPLIT_MS = 2 * 60 * 60 * 1000", self.session)
        self.assertIn("now - lastActiveAt >= IDLE_SPLIT_MS", self.session)

    def test_work_completion_is_sent_back_to_petit(self):
        self.assertIn('kind === "finish"', self.companion)
        self.assertIn("作業終了の振り返り", self.companion)
        self.assertIn("await askPetit(\"finish\")", self.companion)

    def test_voice_and_pwa_assets_remain_wired(self):
        self.assertIn('id="voice-toggle"', self.index)
        self.assertIn('/static/voice.js', self.index)
        self.assertTrue("speechSynthesis" in self.voice or "/api/tts" in self.voice)
        self.assertIn('"display"', self.manifest)
        self.assertIn("self.addEventListener", self.service_worker)


if __name__ == "__main__":
    unittest.main()
