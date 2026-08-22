from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class WorkSessionUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = (FRONTEND / "universe-app.js").read_text(encoding="utf-8")
        cls.today = (FRONTEND / "today.js").read_text(encoding="utf-8")
        cls.html = (FRONTEND / "universe.html").read_text(encoding="utf-8")

    def test_ui_starts_session_with_task_identity(self) -> None:
        self.assertIn("task_id: key", self.app)
        self.assertIn('project_id: text(task.project_id, "") || null', self.app)

    def test_server_active_session_is_restored_and_polled(self) -> None:
        self.assertGreaterEqual(self.app.count('workSessionRequest("/active", "GET")'), 2)
        self.assertNotIn("if (!state.workSessionId) return;", self.app)
        self.assertIn("if (session.task_id)", self.app)
        self.assertIn("if (!session) {", self.app)

    def test_today_renders_task_breakdown(self) -> None:
        self.assertIn('id="today-tasks"', self.html)
        self.assertIn("const tasksData = Array.isArray(data.tasks)", self.today)
        self.assertIn("task.elapsed_seconds", self.today)


if __name__ == "__main__":
    unittest.main()
