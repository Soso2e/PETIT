from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import config, db, project_continuity


class ProjectContinuityStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(config, "DB_PATH", Path(self.temp_dir.name) / "app.db")
        self.db_patch.start()
        db.init_db()
        project_continuity.ensure_project_schema()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def create_episode(self, title: str = "episode") -> int:
        return db.save_episode(
            {
                "started_at": db.now_iso(),
                "ended_at": db.now_iso(),
                "title": title,
                "summary": "summary",
                "decisions": "[]",
                "facts": "[]",
                "work_in_progress": "[]",
                "next_action": "[]",
                "source_ids": "[]",
                "content_hash": f"hash-{title}",
            }
        )

    def test_project_name_is_registered_as_alias_and_duplicate_is_ignored(self) -> None:
        project = project_continuity.create_project("PETIT", project_id="petit")
        self.assertEqual(project["name"], "PETIT")
        self.assertEqual(project_continuity.find_projects_by_alias("ｐｅｔｉｔ")[0]["id"], "petit")
        self.assertFalse(project_continuity.add_project_alias("petit", "petit"))

    def test_same_normalized_alias_can_return_multiple_candidates(self) -> None:
        first = project_continuity.create_project("Project A", project_id="a")
        second = project_continuity.create_project("Project B", project_id="b")
        self.assertTrue(project_continuity.add_project_alias(first["id"], "Webのやつ"))
        self.assertTrue(project_continuity.add_project_alias(second["id"], "Ｗｅｂ のやつ"))

        matches = project_continuity.find_projects_by_alias("webのやつ")

        self.assertEqual({item["id"] for item in matches}, {"a", "b"})

    def test_episode_can_link_to_multiple_projects(self) -> None:
        episode_id = self.create_episode()
        first = project_continuity.create_project("PETIT", project_id="petit")
        second = project_continuity.create_project("Linkraft", project_id="linkraft")

        project_continuity.link_episode_to_project(episode_id, first["id"], relation="primary", confirmed=True)
        project_continuity.link_episode_to_project(episode_id, second["id"], relation="referenced", confidence=0.8)

        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT project_id, relation FROM episode_project_links WHERE episode_id=? ORDER BY project_id",
                (episode_id,),
            ).fetchall()
        self.assertEqual([(row["project_id"], row["relation"]) for row in rows], [("linkraft", "referenced"), ("petit", "primary")])

    def test_active_project_switch_replaces_only_current_state(self) -> None:
        project_continuity.create_project("PETIT", project_id="petit")
        project_continuity.create_project("Linkraft", project_id="linkraft")
        project_continuity.set_active_project("soso", "petit")

        active = project_continuity.set_active_project("soso", "linkraft")

        self.assertIsNotNone(active)
        self.assertEqual(active["project_id"], "linkraft")
        self.assertEqual(active["name"], "Linkraft")
        with db.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM active_project_state WHERE user_id='soso'").fetchone()[0]
        self.assertEqual(count, 1)

    def test_partial_checkpoint_update_preserves_verified_evidence(self) -> None:
        project_continuity.create_project("PETIT", project_id="petit")
        project_continuity.save_project_checkpoint(
            "soso",
            "petit",
            stage="automated_tests_verified",
            last_summary="実装とテストまで完了",
            completed_evidence=["unittest 59件"],
            unverified_items=["実ブラウザ"],
            blockers=["LM Studio停止"],
            source_conversation_ids=[10],
        )

        checkpoint = project_continuity.save_project_checkpoint(
            "soso",
            "petit",
            next_action="LM Studioを起動して実ブラウザ確認",
        )

        self.assertEqual(checkpoint["stage"], "automated_tests_verified")
        self.assertEqual(checkpoint["completed_evidence"], ["unittest 59件"])
        self.assertEqual(checkpoint["unverified_items"], ["実ブラウザ"])
        self.assertEqual(checkpoint["blockers"], ["LM Studio停止"])
        self.assertEqual(checkpoint["source_conversation_ids"], [10])
        self.assertEqual(checkpoint["next_action"], "LM Studioを起動して実ブラウザ確認")

    def test_source_link_requires_confirmation_and_can_be_removed(self) -> None:
        project_continuity.create_project("PETIT", project_id="petit")
        link = project_continuity.link_project_source(
            "petit",
            "github",
            "Soso2e/PETIT",
            external_url="https://github.com/Soso2e/PETIT",
            metadata={"default_branch": "main"},
        )
        self.assertIsNone(link["confirmed_at"])
        self.assertEqual(link["metadata"], {"default_branch": "main"})

        confirmed = project_continuity.confirm_project_source_link(link["id"])
        self.assertIsNotNone(confirmed["confirmed_at"])

        removed = project_continuity.remove_project_source_link(link["id"])
        self.assertEqual(removed["status"], "removed")

    def test_source_cannot_move_to_another_project_without_explicit_removal(self) -> None:
        project_continuity.create_project("PETIT", project_id="petit")
        project_continuity.create_project("Other", project_id="other")
        project_continuity.link_project_source("petit", "github", "Soso2e/PETIT")

        with self.assertRaisesRegex(ValueError, "another project"):
            project_continuity.link_project_source("other", "github", "Soso2e/PETIT")

    def test_existing_database_can_add_continuity_tables_non_destructively(self) -> None:
        with db.get_connection() as conn:
            conn.execute(
                "INSERT INTO memory (created_at, type, content, source) VALUES (?, 'note', 'existing', 'test')",
                (db.now_iso(),),
            )

        project_continuity.ensure_project_schema()

        with db.get_connection() as conn:
            memory = conn.execute("SELECT content FROM memory").fetchone()
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
        self.assertEqual(memory["content"], "existing")
        self.assertTrue({"projects", "project_aliases", "project_source_links", "episode_project_links", "active_project_state", "project_checkpoints"}.issubset(tables))

    def test_invalid_relation_stage_and_confidence_are_rejected(self) -> None:
        episode_id = self.create_episode("validation")
        project_continuity.create_project("PETIT", project_id="petit")
        with self.assertRaises(ValueError):
            project_continuity.link_episode_to_project(episode_id, "petit", relation="owner")
        with self.assertRaises(ValueError):
            project_continuity.link_episode_to_project(episode_id, "petit", confidence=1.1)
        with self.assertRaises(ValueError):
            project_continuity.save_project_checkpoint("soso", "petit", stage="done-ish")


if __name__ == "__main__":
    unittest.main()
