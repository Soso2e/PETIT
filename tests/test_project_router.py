from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import agent, config, db, project_continuity, project_router


class ProjectRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(config, "DB_PATH", Path(self.temp_dir.name) / "app.db")
        self.db_patch.start()
        db.init_db()
        project_continuity.ensure_project_schema()
        project_continuity.create_project("PETIT", project_id="petit")
        project_continuity.add_project_alias("petit", "プチ")
        project_continuity.create_project("Linkraft", project_id="linkraft")
        project_continuity.add_project_alias("linkraft", "リンクラフト")

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_formal_name_and_confirmed_alias_resolve_without_llm(self) -> None:
        formal = project_router.resolve_project("PETIT開発する", user_id="soso")
        alias = project_router.resolve_project("プチ進める", user_id="soso")

        self.assertEqual(formal.kind, "resolved")
        self.assertEqual(formal.project_id, "petit")
        self.assertEqual(alias.kind, "resolved")
        self.assertEqual(alias.project_id, "petit")

    def test_case_spacing_and_particles_are_absorbed(self) -> None:
        resolution = project_router.resolve_project("  次は Ｌｉｎｋｒａｆｔ に戻る！ ", user_id="soso")

        self.assertEqual(resolution.kind, "resolved")
        self.assertEqual(resolution.project_id, "linkraft")

    def test_alias_collision_returns_candidates_and_does_not_switch(self) -> None:
        project_continuity.create_project("Web Portfolio", project_id="web-a")
        project_continuity.create_project("Web Service", project_id="web-b")
        project_continuity.add_project_alias("web-a", "Webのやつ")
        project_continuity.add_project_alias("web-b", "Ｗｅｂ のやつ")
        project_continuity.set_active_project("soso", "petit")

        result = project_router.handle_project_turn("Webのやつやる", user_id="soso")

        self.assertIsNotNone(result)
        self.assertIn("どのプロジェクト", result["reply"])
        self.assertEqual(project_continuity.get_active_project("soso")["project_id"], "petit")
        candidates = result["model_route"]["project_resolution"]["candidates"]
        self.assertEqual({item["id"] for item in candidates}, {"web-a", "web-b"})

    def test_explicit_switch_changes_active_project_and_returns_checkpoint(self) -> None:
        project_continuity.set_active_project("soso", "petit")
        project_continuity.save_project_checkpoint(
            "soso",
            "linkraft",
            last_summary="管理画面の実装まで完了",
            next_action="公開D1へmigrationを適用",
            blockers=["実アカウントE2E未確認"],
        )

        result = project_router.handle_project_turn("リンクラフトやるわ", user_id="soso")

        self.assertIsNotNone(result)
        self.assertEqual(project_continuity.get_active_project("soso")["project_id"], "linkraft")
        self.assertIn("PETITからLinkraft", result["reply"])
        self.assertIn("管理画面の実装まで完了", result["reply"])
        self.assertIn("公開D1へmigrationを適用", result["reply"])

    def test_same_active_project_only_touches_state_and_preserves_checkpoint(self) -> None:
        project_continuity.set_active_project("soso", "petit")
        before = project_continuity.save_project_checkpoint(
            "soso",
            "petit",
            stage="automated_tests_verified",
            completed_evidence=["unittest 59件"],
            unverified_items=["実ブラウザ"],
        )

        result = project_router.handle_project_turn("PETITやる", user_id="soso")
        after = project_continuity.get_project_checkpoint("soso", "petit")

        self.assertIsNotNone(result)
        self.assertIn("続けるんだね", result["reply"])
        self.assertEqual(after["stage"], before["stage"])
        self.assertEqual(after["completed_evidence"], ["unittest 59件"])
        self.assertEqual(after["unverified_items"], ["実ブラウザ"])

    def test_contextual_resume_uses_active_project(self) -> None:
        project_continuity.set_active_project("soso", "linkraft")

        resolution = project_router.resolve_project("さっきの続きやる", user_id="soso")

        self.assertEqual(resolution.kind, "resolved")
        self.assertEqual(resolution.project_id, "linkraft")
        self.assertEqual(resolution.reason, "active_project_context")

    def test_context_without_active_project_requests_clarification(self) -> None:
        result = project_router.handle_project_turn("続きやる", user_id="soso")

        self.assertIsNotNone(result)
        self.assertIn("プロジェクト名を教えて", result["reply"])
        self.assertIsNone(project_continuity.get_active_project("soso"))

    def test_next_one_is_not_guessed_without_recent_candidate(self) -> None:
        project_continuity.set_active_project("soso", "petit")

        result = project_router.handle_project_turn("次のやつやる", user_id="soso")

        self.assertIsNotNone(result)
        self.assertIn("プロジェクト名を教えて", result["reply"])
        self.assertEqual(project_continuity.get_active_project("soso")["project_id"], "petit")

    def test_unknown_explicit_project_name_becomes_candidate_not_auto_created(self) -> None:
        result = project_router.handle_project_turn("Roomies開発する", user_id="soso")

        self.assertIsNotNone(result)
        self.assertIn("まだプロジェクト台帳にない", result["reply"])
        with db.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM projects WHERE name='Roomies'").fetchone()[0]
        self.assertEqual(count, 0)

    def test_ordinary_chat_and_activity_do_not_trigger_project_switch(self) -> None:
        self.assertIsNone(project_router.handle_project_turn("こんにちは", user_id="soso"))
        self.assertIsNone(project_router.handle_project_turn("ゲームやる", user_id="soso"))
        self.assertIsNone(project_continuity.get_active_project("soso"))

    def test_agent_uses_project_fast_path_without_calling_lm_studio(self) -> None:
        with patch("backend.agent.chat_completion", side_effect=AssertionError("LLM must not run")):
            result = agent.run("プチ進める")

        self.assertEqual(result["model_route"]["kind"], "project_continuity")
        self.assertEqual(project_continuity.get_active_project(config.PETIT_OWNER_ID)["project_id"], "petit")
        self.assertIn("PETIT", result["reply"])


if __name__ == "__main__":
    unittest.main()
