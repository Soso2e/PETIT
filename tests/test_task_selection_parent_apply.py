from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class TaskSelectionParentApplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = (FRONTEND / "universe-app.js").read_text(encoding="utf-8")
        self.flow = (FRONTEND / "task-flow.js").read_text(encoding="utf-8")
        self.html = (FRONTEND / "universe.html").read_text(encoding="utf-8")
        self.actions_css = (FRONTEND / "universe-actions.css").read_text(encoding="utf-8")

    def test_life_and_tasks_require_second_activation_before_focus(self) -> None:
        self.assertIn("overviewSelectionId: null", self.app)
        self.assertIn("const selectOverviewTask = (task, index = 0) =>", self.app)
        self.assertIn("const openFocus = state.overviewSelectionId === key", self.app)
        self.assertIn("state.overviewSelectionId = key", self.app)
        self.assertIn('switchView("focus")', self.app)
        self.assertIn("もう一度押すとFocusへ移ります", self.app)

    def test_selection_state_is_visible_and_keyboard_accessible(self) -> None:
        self.assertIn('row.classList.toggle("is-selected", selected)', self.app)
        self.assertIn('row.setAttribute("aria-selected", String(selected))', self.app)
        self.assertIn("row.tabIndex = 0", self.app)
        self.assertIn('row.addEventListener("keydown"', self.app)
        self.assertIn('if (!["Enter", " "].includes(event.key)) return;', self.app)
        self.assertIn('row.setAttribute("aria-pressed", String(selected))', self.app)
        self.assertIn(".task-table tbody tr.is-selected", self.actions_css)
        self.assertIn(".universe-task.is-selected", self.actions_css)

    def test_parent_selection_and_apply_are_separate_actions(self) -> None:
        self.assertIn('data-action="parent"', self.html)
        self.assertIn('data-action="parent-apply" disabled', self.html)
        self.assertIn('document.addEventListener("change", handleParentSelection, true);', self.flow)
        self.assertIn('document.addEventListener("click", handleParentApply, true);', self.flow)
        self.assertIn("まだ保存されていません", self.flow)
        self.assertIn("void changeParent(task, select, applyButton);", self.flow)

    def test_parent_apply_reports_busy_noop_and_failure_states(self) -> None:
        self.assertIn('applyButton.textContent = "適用中…"', self.flow)
        self.assertIn("現在の親Taskから変更はありません。", self.flow)
        self.assertIn("親子関係を変更できませんでした", self.flow)
        self.assertIn('select.value = String(task.parent_task_id || "")', self.flow)
        self.assertIn('applyButton.textContent = "親Taskを変更"', self.flow)


if __name__ == "__main__":
    unittest.main()
