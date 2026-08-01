from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import config, db, project_continuity, tools


class ProjectStatusToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(config, "DB_PATH", Path(self.temp_dir.name) / "app.db")
        self.db_patch.start()
        db.init_db()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_lists_current_and_incomplete_projects_with_checkpoint_facts(self) -> None:
        project_continuity.create_project("PETIT", project_id="petit")
        project_continuity.create_project("完了済み", project_id="done")
        project_continuity.save_project_checkpoint(
            config.PETIT_OWNER_ID,
            "petit",
            stage="implemented",
            last_summary="会話ランタイムを改善中",
            next_action="ブラウザで確認する",
            blockers=["実モデルE2E"],
        )
        project_continuity.save_project_checkpoint(
            config.PETIT_OWNER_ID,
            "done",
            stage="completed",
            last_summary="完了",
        )
        project_continuity.set_active_project(config.PETIT_OWNER_ID, "petit")

        result = json.loads(tools.dispatch("get_project_status", {}))

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["projects"][0]["name"], "PETIT")
        self.assertTrue(result["projects"][0]["is_current"])
        self.assertEqual(result["projects"][0]["last_summary"], "会話ランタイムを改善中")
        self.assertEqual(result["projects"][0]["next_action"], "ブラウザで確認する")
        self.assertEqual(result["projects"][0]["blockers"], ["実モデルE2E"])

    def test_specific_completed_project_can_be_read(self) -> None:
        project_continuity.create_project("完了済み", project_id="done")
        project_continuity.save_project_checkpoint(
            config.PETIT_OWNER_ID,
            "done",
            stage="completed",
            last_summary="公開済み",
        )

        result = json.loads(tools.dispatch("get_project_status", {"project_id": "done"}))

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["projects"][0]["stage"], "completed")


if __name__ == "__main__":
    unittest.main()
