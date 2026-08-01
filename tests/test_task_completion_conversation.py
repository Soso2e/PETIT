from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import agent, config, db, main, project_completion, project_continuity, task_completion


class TaskCompletionConversationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(config, "DB_PATH", Path(self.temp_dir.name) / "app.db")
        self.db_patch.start()
        db.init_db()
        task_completion.ensure_schema()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def add_task(self, title: str, status: str = "Yet") -> int:
        with db.get_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO tasks_cache (source, title, status, priority, updated_at) "
                "VALUES ('notion', ?, ?, 'High', ?)",
                (title, status, db.now_iso()),
            )
            return int(cursor.lastrowid)

    def test_named_completion_resolves_unique_active_task_before_project_flow(self) -> None:
        task_id = self.add_task("LiTのデザイン実装")
        self.add_task("LiT課題", status="Done")

        with patch("backend.agent.chat_completion", side_effect=AssertionError("LLM must not run")):
            result = agent.run("LiTデザインは完了した！")

        self.assertEqual(result["model_route"]["kind"], "task_completion_preview")
        self.assertIn("LiTのデザイン実装", result["reply"])
        action = result["pending_actions"][0]
        self.assertEqual(action["name"], "complete_task")
        self.assertEqual(action["arguments"]["task_id"], task_id)
        self.assertEqual(action["arguments"]["title_query"], "LiTのデザイン実装")

    def test_additive_particle_and_casual_ending_resolve_named_task(self) -> None:
        task_id = self.add_task("キャンプの予習")

        with patch("backend.agent.chat_completion", side_effect=AssertionError("LLM must not run")):
            result = agent.run("キャンプの予習も終わったわ")

        self.assertEqual(result["model_route"]["kind"], "task_completion_preview")
        self.assertIn("キャンプの予習", result["reply"])
        action = result["pending_actions"][0]
        self.assertEqual(action["name"], "complete_task")
        self.assertEqual(action["arguments"]["task_id"], task_id)
        self.assertEqual(action["arguments"]["title_query"], "キャンプの予習")

    def test_ambiguous_candidates_are_listed_once_and_followup_number_selects(self) -> None:
        first_id = self.add_task("LiTデザイン実装")
        self.add_task("LiTデザイン確認")

        first = task_completion.try_handle_task_completion_turn(
            "LiTデザインは完了した！",
            user_id=config.PETIT_OWNER_ID,
        )
        second = task_completion.try_handle_task_completion_turn(
            "2",
            user_id=config.PETIT_OWNER_ID,
        )

        self.assertEqual(first["model_route"]["kind"], "task_completion_candidates")
        self.assertIn("1.", first["reply"])
        self.assertEqual(second["model_route"]["kind"], "task_completion_preview")
        self.assertTrue(second["model_route"]["selected_from_draft"])
        self.assertEqual(second["pending_actions"][0]["arguments"]["task_id"], first_id)

    def test_already_done_task_does_not_offer_another_write(self) -> None:
        self.add_task("LiTのデザイン実装", status="Done")

        result = task_completion.try_handle_task_completion_turn(
            "LiTデザインは完了した！",
            user_id=config.PETIT_OWNER_ID,
        )

        self.assertEqual(result["model_route"]["kind"], "task_completion_already_done")
        self.assertIn("すでに完了", result["reply"])
        self.assertNotIn("pending_actions", result)

    def test_named_but_unknown_task_gets_one_short_recovery_question(self) -> None:
        result = task_completion.try_handle_task_completion_turn(
            "卒研レポートは完了した！",
            user_id=config.PETIT_OWNER_ID,
        )

        self.assertEqual(result["model_route"]["kind"], "task_completion_not_found")
        self.assertIn("別の名前", result["reply"])

    def test_explicit_project_completion_is_left_for_project_continuity(self) -> None:
        result = task_completion.try_handle_task_completion_turn(
            "PETITプロジェクトの作業が完了した",
            user_id=config.PETIT_OWNER_ID,
        )

        self.assertIsNone(result)

    def test_existing_project_completion_draft_keeps_ownership_of_followup(self) -> None:
        project_continuity.ensure_project_schema()
        project_completion.ensure_completion_schema()
        project_continuity.create_project("PETIT", project_id="petit")
        project_continuity.set_active_project(config.PETIT_OWNER_ID, "petit")
        first = agent.run("終わった")

        second = agent.run("実装だけ終わった。ブラウザ確認はまだ")

        self.assertEqual(first["model_route"]["kind"], "project_completion_clarification")
        self.assertEqual(second["model_route"]["kind"], "project_completion_preview")
        self.assertEqual(second["pending_actions"][0]["name"], "save_project_completion")

    def test_named_active_project_without_task_match_stays_on_project_flow(self) -> None:
        project_continuity.ensure_project_schema()
        project_completion.ensure_completion_schema()
        project_continuity.create_project("PETIT", project_id="petit")
        project_continuity.set_active_project(config.PETIT_OWNER_ID, "petit")

        result = agent.run("PETITの作業が完了した")

        self.assertEqual(result["model_route"]["kind"], "project_completion_clarification")
        self.assertNotIn("近い未完了タスク", result["reply"])

    def test_approved_completion_has_a_natural_result(self) -> None:
        task_id = self.add_task("LiTのデザイン実装")
        pending = main._register_pending_actions(
            [
                {
                    "name": "complete_task",
                    "arguments": {"task_id": task_id, "title_query": "LiTのデザイン実装"},
                }
            ]
        )[0]

        response = main.decide_action(pending.approval_id, main.ActionDecision(approved=True))

        self.assertEqual(response.reply, "「LiTのデザイン実装」を完了にしたよ。おつかれさま！")
        self.assertNotIn("{", response.reply)


if __name__ == "__main__":
    unittest.main()
