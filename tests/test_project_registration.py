from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import config, db, project_continuity, project_registration, tools


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



    def test_explicit_registration_command_uses_same_confirmation_path(self) -> None:
        result = project_registration.try_handle_registration_turn(
            "『Cooking Combat』をプロジェクト登録して",
            user_id="soso",
        )

        self.assertIsNotNone(result)
        args = self._pending(result, "create_internal_project")
        self.assertEqual(args["name"], "Cooking Combat")
        self.assertEqual(project_continuity.find_projects_by_alias("Cooking Combat"), [])



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




if __name__ == "__main__":
    unittest.main()
