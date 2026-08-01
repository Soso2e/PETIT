from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import agent, config, db, project_completion, project_continuity, tools


class ProjectCompletionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(config, "DB_PATH", Path(self.temp_dir.name) / "app.db")
        self.db_patch.start()
        db.init_db()
        project_continuity.ensure_project_schema()
        project_completion.ensure_completion_schema()
        project_continuity.create_project("PETIT", project_id="petit")
        project_continuity.set_active_project(config.PETIT_OWNER_ID, "petit")

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def _pending_args(self, result: dict) -> dict:
        self.assertEqual(len(result.get("pending_actions") or []), 1)
        action = result["pending_actions"][0]
        self.assertEqual(action["name"], "save_project_completion")
        return action["arguments"]

    def test_vague_finished_starts_draft_without_checkpoint(self) -> None:
        result = project_completion.try_handle_completion_turn(
            "終わった",
            user_id=config.PETIT_OWNER_ID,
            recent_history=[{"role": "user", "content": "朝ブリーフィングの実装を進めてる"}],
        )

        self.assertIsNotNone(result)
        self.assertIn("実装まで", result["reply"])
        self.assertIsNotNone(project_completion.get_completion_draft(config.PETIT_OWNER_ID))
        self.assertIsNone(project_continuity.get_project_checkpoint(config.PETIT_OWNER_ID, "petit"))
        self.assertFalse(result.get("pending_actions"))

    def test_scope_answer_creates_preview_but_does_not_save(self) -> None:
        project_completion.try_handle_completion_turn("終わった", user_id=config.PETIT_OWNER_ID)

        result = project_completion.try_handle_completion_turn(
            "実装だけ終わった。ブラウザ確認はまだ",
            user_id=config.PETIT_OWNER_ID,
        )
        args = self._pending_args(result)

        self.assertEqual(args["stage"], "implemented")
        self.assertIn("実画面確認", args["unverified_items"])
        self.assertIn("自動テスト", args["unverified_items"])
        self.assertIsNone(project_continuity.get_project_checkpoint(config.PETIT_OWNER_ID, "petit"))
        self.assertIsNone(project_completion.get_completion_draft(config.PETIT_OWNER_ID))

    def test_approved_tool_saves_checkpoint_and_event_once(self) -> None:
        project_continuity.save_project_checkpoint(
            config.PETIT_OWNER_ID,
            "petit",
            source_conversation_ids=[99],
        )
        project_completion.try_handle_completion_turn("終わった", user_id=config.PETIT_OWNER_ID)
        preview = project_completion.try_handle_completion_turn(
            "テストも通った。次はブラウザで確認する",
            user_id=config.PETIT_OWNER_ID,
        )
        args = self._pending_args(preview)
        conversation_id = db.save_conversation(args["source_user_text"], preview["reply"], session_id="test")

        first = json.loads(tools.dispatch("save_project_completion", args))
        second = json.loads(tools.dispatch("save_project_completion", args))

        self.assertTrue(first["saved"])
        self.assertFalse(first["idempotency_hit"])
        self.assertTrue(second["idempotency_hit"])
        checkpoint = project_continuity.get_project_checkpoint(config.PETIT_OWNER_ID, "petit")
        self.assertEqual(checkpoint["stage"], "automated_tests_verified")
        self.assertEqual(checkpoint["next_action"], "ブラウザで確認する")
        self.assertIn("実画面確認", checkpoint["unverified_items"])
        self.assertEqual(checkpoint["source_conversation_ids"], [99, conversation_id])
        with db.get_connection() as conn:
            events = conn.execute("SELECT event_type, provider, source_conversation_id FROM project_events").fetchall()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "tests_verified")
        self.assertEqual(events[0]["provider"], "petit")
        self.assertEqual(events[0]["source_conversation_id"], conversation_id)

    def test_deployed_does_not_invent_tests_ui_or_production_evidence(self) -> None:
        result = project_completion.try_handle_completion_turn(
            "デプロイしたけど本番確認はまだ",
            user_id=config.PETIT_OWNER_ID,
        )
        args = self._pending_args(result)

        self.assertEqual(args["stage"], "deployed")
        self.assertIn("本番確認", args["unverified_items"])
        self.assertIn("自動テスト", args["unverified_items"])
        self.assertIn("実画面確認", args["unverified_items"])
        self.assertIn("デプロイ済み（ユーザー確認）", args["completed_evidence"])
        self.assertNotIn("自動テスト確認済み（ユーザー確認）", args["completed_evidence"])
        self.assertNotIn("実画面確認済み（ユーザー確認）", args["completed_evidence"])
        self.assertNotIn("本番確認済み（ユーザー確認）", args["completed_evidence"])

    def test_explicit_complete_can_clear_remaining_items(self) -> None:
        project_continuity.save_project_checkpoint(
            config.PETIT_OWNER_ID,
            "petit",
            blockers=["旧ブロッカー"],
            unverified_items=["自動テスト", "本番確認"],
        )

        result = project_completion.try_handle_completion_turn(
            "全部終わって完全に完了した",
            user_id=config.PETIT_OWNER_ID,
        )
        args = self._pending_args(result)

        self.assertEqual(args["stage"], "completed")
        self.assertEqual(args["unverified_items"], [])
        self.assertEqual(args["blockers"], [])
        self.assertIn("完全完了（ユーザー確認）", args["completed_evidence"])

    def test_today_is_done_is_paused_not_completed(self) -> None:
        result = project_completion.try_handle_completion_turn("今日はここまで", user_id=config.PETIT_OWNER_ID)
        args = self._pending_args(result)

        self.assertEqual(args["stage"], "paused")
        self.assertEqual(args["event_type"], "paused")

    def test_blocker_is_recorded_separately(self) -> None:
        result = project_completion.try_handle_completion_turn(
            "エラーで詰まったから今日はここまで",
            user_id=config.PETIT_OWNER_ID,
        )
        args = self._pending_args(result)

        self.assertEqual(args["stage"], "blocked")
        self.assertTrue(args["blockers"])

    def test_missing_active_project_asks_for_name(self) -> None:
        project_continuity.set_active_project(config.PETIT_OWNER_ID, None)

        result = project_completion.try_handle_completion_turn("終わった", user_id=config.PETIT_OWNER_ID)

        self.assertIsNotNone(result)
        self.assertIn("どのプロジェクト", result["reply"])
        self.assertFalse(result.get("pending_actions"))

    def test_named_completion_without_active_project_is_not_forced_into_project_fallback(self) -> None:
        project_continuity.set_active_project(config.PETIT_OWNER_ID, None)

        result = project_completion.try_handle_completion_turn(
            "キャンプの予習も終わったわ",
            user_id=config.PETIT_OWNER_ID,
        )

        self.assertIsNone(result)

    def test_task_completion_command_stays_on_existing_tool_path(self) -> None:
        result = project_completion.try_handle_completion_turn(
            "このタスクを完了にして",
            user_id=config.PETIT_OWNER_ID,
        )

        self.assertIsNone(result)

    def test_agent_completion_path_does_not_call_lm_studio(self) -> None:
        with patch("backend.agent.chat_completion", side_effect=AssertionError("LLM must not run")):
            result = agent.run("終わった")

        self.assertEqual(result["model_route"]["kind"], "project_completion_clarification")
        self.assertIsNotNone(project_completion.get_completion_draft(config.PETIT_OWNER_ID))


if __name__ == "__main__":
    unittest.main()
