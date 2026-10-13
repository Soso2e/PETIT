from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class UnivHomeFlowAssetTests(unittest.TestCase):
    def test_univ_is_the_app_shell_home(self) -> None:
        shell = (FRONTEND / "app_shell.js").read_text(encoding="utf-8")
        self.assertIn('const HOME_VIEW = "universe"', shell)
        self.assertIn('{ view: "univ", target: "universe", label: "Univ", title: "Universe"', shell)
        self.assertIn('home: "univ"', shell)
        self.assertIn('focus: "univ"', shell)
        self.assertIn('activateView(initialView)', shell)

    def test_univ_focus_uses_same_space_instead_of_view_transition(self) -> None:
        life_script = (FRONTEND / "life-map.js").read_text(encoding="utf-8")
        motion_script = (FRONTEND / "petit-motion.js").read_text(encoding="utf-8")
        style = (FRONTEND / "life-transition.css").read_text(encoding="utf-8")
        univ = (FRONTEND / "univ-space.js").read_text(encoding="utf-8")
        self.assertNotIn("life-dive-portal", life_script)
        self.assertNotIn("replayClick(target)", life_script)
        self.assertNotIn("performTransition", motion_script)
        self.assertIn("replayViewFade", motion_script)
        self.assertNotIn("data-petit-transition-from", style)
        self.assertIn("is-univ-focus-target", univ)
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

    def test_today_is_available_as_work_statistics(self) -> None:
        script = (FRONTEND / "today.js").read_text(encoding="utf-8")
        style = (FRONTEND / "statistics.css").read_text(encoding="utf-8")
        shell = (FRONTEND / "app_shell.js").read_text(encoding="utf-8")
        self.assertIn('today: "stats"', shell)
        self.assertIn("today-session-count", script)
        self.assertIn("/api/work-sessions/summary?days=7", script)
        self.assertIn(".stats-metrics", style)
        self.assertIn(".stats-week-bar", style)


if __name__ == "__main__":
    unittest.main()
