from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import brain_project_sync, config, db, project_continuity, vault_indexer


class BrainCandidateDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "Vault"
        self.root.mkdir()
        self.note = self.root / "Projects" / "PETIT.md"
        self.note.parent.mkdir(parents=True)
        self.note.write_text("# PETIT\n\nローカルAIアシスタントの設計ノート。\n", encoding="utf-8")
        self.db_patch = patch.object(config, "DB_PATH", Path(self.temp_dir.name) / "app.db")
        self.vault_patch = patch.object(config, "OBSIDIAN_VAULT_DIRS", [self.root])
        self.db_patch.start()
        self.vault_patch.start()
        vault_indexer._TEXT_CACHE.clear()
        db.init_db()
        project_continuity.ensure_project_schema()
        brain_project_sync.ensure_brain_project_schema()
        project_continuity.create_project("PETIT", project_id="petit")

    def tearDown(self) -> None:
        self.vault_patch.stop()
        self.db_patch.stop()
        vault_indexer._TEXT_CACHE.clear()
        self.temp_dir.cleanup()

    def test_keyword_search_finds_note(self) -> None:
        results = vault_indexer.keyword_search("PETIT", limit=10)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["relative_path"], "Projects/PETIT.md")

    def test_source_path_resolves_to_vault_relative_note(self) -> None:
        result = vault_indexer.keyword_search("PETIT", limit=10)[0]
        vault_index, relative_path = brain_project_sync._vault_index_for_path(result["source_path"])
        self.assertEqual(vault_index, 0)
        self.assertEqual(Path(relative_path).as_posix(), "Projects/PETIT.md")

    def test_note_data_is_safe_and_bounded(self) -> None:
        data = brain_project_sync._note_data(0, "Projects/PETIT.md")
        self.assertEqual(data["external_id"], "vault:0:Projects/PETIT.md")
        self.assertEqual(data["title"], "PETIT")
        self.assertLessEqual(len(data["excerpt"]), 1200)

    def test_candidate_upsert_round_trips(self) -> None:
        data = brain_project_sync._note_data(0, "Projects/PETIT.md")
        candidate = brain_project_sync._upsert_candidate(
            data,
            suggested_project_ids=["petit"],
            match_reason="project_term:PETIT",
        )
        self.assertEqual(candidate["external_id"], "vault:0:Projects/PETIT.md")
        self.assertEqual(candidate["suggested_project_ids"], ["petit"])
        self.assertEqual(candidate["status"], "pending")

    def test_full_discovery_returns_one_candidate(self) -> None:
        result = brain_project_sync.discover_project_candidates("petit")
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["candidates"][0]["relative_path"], "Projects/PETIT.md")


if __name__ == "__main__":
    unittest.main()
