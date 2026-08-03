from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class LifeHomeFlowAssetTests(unittest.TestCase):
    def test_life_is_the_app_shell_home(self) -> None:
        shell = (FRONTEND / "app_shell.js").read_text(encoding="utf-8")
        self.assertIn('const HOME_VIEW = "universe"', shell)
        self.assertIn('const PRIMARY_VIEWS = ["universe", "focus", "tasks", "chat"]', shell)
        self.assertIn('{ view: "today", label: "Today" }', shell)
        self.assertIn('activateView(initialView)', shell)

    def test_life_to_focus_uses_shared_motion_coordinator(self) -> None:
        life_script = (FRONTEND / "life-map.js").read_text(encoding="utf-8")
        motion_script = (FRONTEND / "petit-motion.js").read_text(encoding="utf-8")
        style = (FRONTEND / "life-transition.css").read_text(encoding="utf-8")
        self.assertNotIn("life-dive-portal", life_script)
        self.assertNotIn("replayClick(target)", life_script)
        self.assertIn("petit-motion.js", life_script)
        self.assertIn("transitionTaskToFocus", motion_script)
        self.assertIn("await activate();", motion_script)
        self.assertIn("data-petit-transition-from", style)
        self.assertIn("prefers-reduced-motion: reduce", style)

    def test_parent_flow_and_child_composer_are_loaded(self) -> None:
        shell = (FRONTEND / "app_shell.js").read_text(encoding="utf-8")
        script = (FRONTEND / "task-flow.js").read_text(encoding="utf-8")
        self.assertIn('/static/task-flow.js', shell)
        self.assertIn('/static/task-flow.css', shell)
        self.assertIn('/parent`', script)
        self.assertIn('/children`', script)
        self.assertIn("await refreshAndFocusTask(taskId(task))", script)
        self.assertIn("window.PetitUniverse.refreshAndFocusTask", script)
        self.assertIn("この親Taskに小タスクを追加", script)

    def test_today_dashboard_has_actions_and_metrics(self) -> None:
        script = (FRONTEND / "today.js").read_text(encoding="utf-8")
        style = (FRONTEND / "today.css").read_text(encoding="utf-8")
        self.assertIn('id = "today-metrics"', script)
        self.assertIn("today-session-count", script)
        self.assertIn('data-today-go="universe"', script)
        self.assertIn(".today-card--metrics", style)
        self.assertIn(".today-quick-actions", style)


if __name__ == "__main__":
    unittest.main()
