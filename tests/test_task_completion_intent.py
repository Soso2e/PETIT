from __future__ import annotations

import unittest
from unittest.mock import patch

from backend import agent, task_completion_intent


class TaskCompletionIntentTests(unittest.TestCase):
    def test_named_completion_extracts_target(self) -> None:
        self.assertEqual(task_completion_intent.extract_target("LiTデザインは完了した！"), "LiTデザイン")
        self.assertEqual(task_completion_intent.extract_target("資料作成を終えました"), "資料作成")

    def test_explicit_project_completion_is_not_intercepted(self) -> None:
        self.assertIsNone(task_completion_intent.extract_target("PETITプロジェクトは完了した"))

    @patch("backend.task_completion_intent.tools.dispatch")
    @patch("backend.task_completion_intent._candidate_rows")
    def test_unique_candidate_is_completed_on_first_turn(self, rows, dispatch) -> None:
        rows.return_value = (
            [
                {
                    "id": 42,
                    "title": "LiTのデザイン実装",
                    "status": "Ready",
                    "source": "notion",
                    "match_score": 87,
                }
            ],
            [],
        )

        dispatch.return_value = '{"completed": true, "task": {"title": "LiTのデザイン実装"}}'

        result = task_completion_intent.try_handle("LiTデザインは完了した！")

        self.assertEqual(result["reply"], "「LiTのデザイン実装」を完了にしたよ。")
        self.assertEqual(
            [item["name"] for item in result["used_tools"]],
            ["get_tasks", "complete_task"],
        )
        self.assertNotIn("pending_actions", result)
        dispatch.assert_called_once_with("complete_task", {"task_id": 42})

    @patch("backend.task_completion_intent.tools.dispatch", return_value='{"completed": false}')
    @patch("backend.task_completion_intent._candidate_rows")
    def test_unique_candidate_reports_write_failure(self, rows, _dispatch) -> None:
        rows.return_value = (
            [{"id": 42, "title": "LiTのデザイン実装", "match_score": 87}],
            [],
        )

        result = task_completion_intent.try_handle("LiTデザインは完了した！")

        self.assertIn("完了にできなかった", result["reply"])
        self.assertFalse(result["persist"])
        self.assertNotIn("pending_actions", result)

    @patch("backend.task_completion_intent._candidate_rows")
    def test_multiple_candidates_are_presented_without_write(self, rows) -> None:
        rows.return_value = (
            [
                {"id": 1, "title": "LiTデザインA", "match_score": 90},
                {"id": 2, "title": "LiTデザインB", "match_score": 90},
            ],
            [],
        )

        result = task_completion_intent.try_handle("LiTデザインは完了した")

        self.assertIn("候補が複数あります", result["reply"])
        self.assertNotIn("pending_actions", result)

    @patch("backend.task_completion_intent._candidate_rows")
    def test_completed_candidate_returns_natural_reply(self, rows) -> None:
        rows.return_value = (
            [],
            [{"id": 42, "title": "LiTのデザイン実装", "match_score": 87}],
        )

        result = task_completion_intent.try_handle("LiTデザインは完了した")

        self.assertEqual(result["reply"], "「LiTのデザイン実装」はすでに完了になっています。")

    @patch("backend.agent.task_completion_intent.try_handle")
    @patch("backend.agent.project_router.try_handle_project_turn")
    def test_task_completion_runs_before_project_continuity(self, project_turn, task_turn) -> None:
        task_turn.return_value = {"reply": "task route", "used_tools": []}

        result = agent.run("LiTデザインは完了した！")

        self.assertEqual(result["reply"], "task route")
        project_turn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
