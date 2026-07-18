from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import agent, config, db, project_continuity, project_registration, project_router, tools


class ProjectRegistrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(config, "DB_PATH", Path(self.temp_dir.name) / "app.db")
        self.db_patch.start()
        db.init_db()
        project_continuity.ensure_project_schema()
        project_registration.ensure_registration_schema()
        project_continuity.create_project("PETIT", project_id="petit")

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def _pending(self, result: dict, name: str) -> dict:
        self.assertEqual(len(result.get("pending_actions") or []), 1)
        action = result["pending_actions"][0]
        self.assertEqual(action["name"], name)
        return action["arguments"]

    def test_unknown_project_work_turn_creates_preview_without_writing(self) -> None:
        result = project_router.handle_project_turn("Roomies開発する", user_id="soso")
        args = self._pending(result, "create_internal_project")

        self.assertIn("新規プロジェクトとして登録", result["reply"])
        self.assertEqual(args["name"], "Roomies")
        self.assertEqual(project_continuity.find_projects_by_alias("Roomies"), [])
        self.assertIsNone(project_continuity.get_active_project("soso"))

    def test_approval_creates_and_activates_project_idempotently(self) -> None:
        preview = project_router.handle_project_turn("Roomies開発する", user_id="soso")
        args = self._pending(preview, "create_internal_project")

        first = json.loads(tools.dispatch("create_internal_project", args))
        second = json.loads(tools.dispatch("create_internal_project", args))

        self.assertTrue(first["created"])
        self.assertFalse(first["idempotency_hit"])
        self.assertTrue(second["idempotency_hit"])
        matches = project_continuity.find_projects_by_alias("Roomies")
        self.assertEqual(len(matches), 1)
        self.assertEqual(project_continuity.get_active_project("soso")["project_id"], matches[0]["id"])
        with db.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM projects WHERE name='Roomies'").fetchone()[0]
        self.assertEqual(count, 1)

    def test_explicit_registration_command_uses_same_confirmation_path(self) -> None:
        result = project_registration.try_handle_registration_turn(
            "『Cooking Combat』をプロジェクト登録して",
            user_id="soso",
        )

        self.assertIsNotNone(result)
        args = self._pending(result, "create_internal_project")
        self.assertEqual(args["name"], "Cooking Combat")
        self.assertEqual(project_continuity.find_projects_by_alias("Cooking Combat"), [])

    def test_alias_is_added_only_after_approval(self) -> None:
        result = project_registration.try_handle_registration_turn(
            "「プチ」をPETITの別名にして",
            user_id="soso",
        )
        args = self._pending(result, "add_internal_project_alias")

        self.assertEqual(project_continuity.find_projects_by_alias("プチ"), [])
        saved = json.loads(tools.dispatch("add_internal_project_alias", args))
        replay = json.loads(tools.dispatch("add_internal_project_alias", args))

        self.assertTrue(saved["added"])
        self.assertTrue(replay["idempotency_hit"])
        matches = project_continuity.find_projects_by_alias("プチ")
        self.assertEqual([item["id"] for item in matches], ["petit"])
        resolution = project_router.resolve_project("プチ進める", user_id="soso")
        self.assertEqual(resolution.project_id, "petit")

    def test_alias_collision_is_disclosed_and_becomes_ambiguous_after_approval(self) -> None:
        project_continuity.create_project("Portfolio", project_id="portfolio")
        project_continuity.add_project_alias("portfolio", "プチ")

        preview = project_registration.try_handle_registration_turn(
            "プチをPETITの別名にして",
            user_id="soso",
        )
        args = self._pending(preview, "add_internal_project_alias")

        self.assertIn("候補確認が必要", preview["reply"])
        saved = json.loads(tools.dispatch("add_internal_project_alias", args))
        self.assertEqual(saved["collision_project_ids"], ["portfolio"])
        resolution = project_router.resolve_project("プチ進める", user_id="soso")
        self.assertEqual(resolution.kind, "ambiguous")
        self.assertEqual({item["id"] for item in resolution.candidates}, {"petit", "portfolio"})

    def test_existing_project_name_offers_activation_instead_of_duplicate(self) -> None:
        result = project_registration.preview_new_project("PETIT", user_id="soso")
        args = self._pending(result, "activate_internal_project")

        self.assertIn("既に", result["reply"])
        activated = json.loads(tools.dispatch("activate_internal_project", args))
        self.assertTrue(activated["activated"])
        self.assertEqual(project_continuity.get_active_project("soso")["project_id"], "petit")
        with db.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM projects WHERE name='PETIT'").fetchone()[0]
        self.assertEqual(count, 1)

    def test_cancelled_preview_has_no_side_effect(self) -> None:
        project_router.handle_project_turn("Roomies開発する", user_id="soso")

        self.assertEqual(project_continuity.find_projects_by_alias("Roomies"), [])
        self.assertIsNone(project_continuity.get_active_project("soso"))

    def test_agent_registration_path_does_not_call_lm_studio(self) -> None:
        with patch("backend.agent.chat_completion", side_effect=AssertionError("LLM must not run")):
            result = agent.run("Roomies開発する")

        self.assertEqual(result["model_route"]["kind"], "project_registration_preview")
        self._pending(result, "create_internal_project")


if __name__ == "__main__":
    unittest.main()
