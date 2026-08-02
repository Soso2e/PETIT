from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
BACKEND = ROOT / "backend"


class ReminderUiTests(unittest.TestCase):
    def test_universe_has_reminder_view_and_assets(self) -> None:
        html = (FRONTEND / "universe.html").read_text(encoding="utf-8")
        self.assertIn('data-view="reminders"', html)
        self.assertIn('data-view-panel="reminders"', html)
        self.assertIn('id="reminder-list"', html)
        self.assertIn('/static/reminders.css', html)
        self.assertIn('/static/reminders.js', html)
        self.assertTrue((FRONTEND / "reminders.css").is_file())
        self.assertTrue((FRONTEND / "reminders.js").is_file())

    def test_reminder_ui_uses_safe_dom_and_backend_contract(self) -> None:
        script = (FRONTEND / "reminders.js").read_text(encoding="utf-8")
        self.assertIn("/api/notifications/reminders", script)
        self.assertIn('${encodeURIComponent(reminder.id)}/${action}', script)
        self.assertIn('action === "snooze"', script)
        self.assertIn('actionButton("完了", "complete"', script)
        self.assertIn('actionButton("10分後", "snooze"', script)
        self.assertIn('actionButton("取消", "cancel"', script)
        self.assertIn("textContent", script)
        self.assertNotIn("innerHTML", script)

    def test_conversation_tools_and_backend_exist(self) -> None:
        self.assertTrue((BACKEND / "reminders.py").is_file())
        tool = (BACKEND / "tools" / "reminders.py").read_text(encoding="utf-8")
        tools_init = (BACKEND / "tools" / "__init__.py").read_text(encoding="utf-8")
        capability = (BACKEND / "capability_router.py").read_text(encoding="utf-8")
        self.assertIn('name="create_reminder"', tool)
        self.assertIn('name="get_reminders"', tool)
        self.assertIn('name="manage_reminder"', tool)
        self.assertIn("requires_confirmation=True", tool)
        self.assertIn("reminders", tools_init)
        self.assertIn('"create_reminder"', capability)

    def test_service_worker_precaches_reminder_assets(self) -> None:
        service_worker = (FRONTEND / "service-worker.js").read_text(encoding="utf-8")
        self.assertIn('/static/reminders.css', service_worker)
        self.assertIn('/static/reminders.js', service_worker)


if __name__ == "__main__":
    unittest.main()
