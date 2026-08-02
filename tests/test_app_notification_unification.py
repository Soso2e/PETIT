from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AppNotificationUnificationTests(unittest.TestCase):
    def test_reminder_tool_does_not_create_calendar_event(self):
        source = (ROOT / "backend" / "tools" / "reminders.py").read_text(encoding="utf-8")
        self.assertIn("カレンダー予定は作成しない", source)
        self.assertIn("add_scheduleを使わない", source)
        self.assertIn("20:30になったら帰ろうかな", source)

    def test_reminders_dispatch_through_shared_notification_service(self):
        source = (ROOT / "backend" / "reminders.py").read_text(encoding="utf-8")
        self.assertIn("notifications.dispatch_notification", source)
        self.assertIn('category="schedule_reminder"', source)
        self.assertIn("delivery_event_id", source)

    def test_work_sessions_are_server_backed(self):
        source = (ROOT / "frontend" / "universe-app.js").read_text(encoding="utf-8")
        self.assertIn("/api/work-sessions", source)
        self.assertIn("workSessionId", source)
        self.assertIn('localStorage.removeItem("petit_universe_active_started_at")', source)

    def test_conversation_idle_boundary_is_two_hours(self):
        session = (ROOT / "frontend" / "session.js").read_text(encoding="utf-8")
        self.assertIn("2 * 60 * 60 * 1000", session)
        self.assertIn("now - lastActiveAt >= IDLE_SPLIT_MS", session)

    def test_universe_uses_shared_chat_input(self):
        html = (ROOT / "frontend" / "universe.html").read_text(encoding="utf-8")
        self.assertIn('/static/chat_input.js', html)
        self.assertNotIn('/static/chat_keyboard.js', html)

    def test_universe_app_shell_has_life_first_primary_navigation(self):
        source = (ROOT / "frontend" / "app_shell.js").read_text(encoding="utf-8")
        self.assertIn('const PRIMARY_VIEWS = ["universe", "focus", "tasks", "chat"]', source)
        self.assertIn('{ view: "today", label: "Today" }', source)
        self.assertIn('moreButton.textContent = "More"', source)
        self.assertIn('Calendar（read-only）', source)
        self.assertIn('Reminders', source)

    def test_shared_chat_bootstraps_app_shell_only_for_universe(self):
        source = (ROOT / "frontend" / "chat_input.js").read_text(encoding="utf-8")
        self.assertIn('document.querySelector(".universe-shell")', source)
        self.assertIn('/static/app_shell.js', source)
        self.assertIn('data-petit-module', source)


if __name__ == "__main__":
    unittest.main()
