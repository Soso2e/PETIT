from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import (
    brain_project_sync,
    config,
    db,
    project_continuity,
    project_resume,
    project_source_refresh,
    vault_indexer,
)
from backend.tools.registry import registered_names, requires_confirmation


class BrainProjectMappingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "Vault"
        self.root.mkdir()
        self.db_patch = patch.object(config, "DB_PATH", Path(self.temp_dir.name) / "app.db")
        self.vault_patch = patch.object(config, "OBSIDIAN_VAULT_DIRS", [self.root])
        self.db_patch.start()
        self.vault_patch.start()
        vault_indexer._TEXT_CACHE.clear()
        db.init_db()
        project_continuity.ensure_project_schema()
        brain_project_sync.ensure_brain_project_schema()

    def tearDown(self) -> None:
        self.vault_patch.stop()
        self.db_patch.stop()
        vault_indexer._TEXT_CACHE.clear()
        self.temp_dir.cleanup()

    def write_note(self, relative_path: str, content: str) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        vault_indexer._TEXT_CACHE.pop(str(path), None)
        return path

    def make_project_note(self) -> Path:
        return self.write_note(
            "Projects/PETIT.md",
            "# PETIT\n\nローカルAIアシスタントの設計ノート。\n\n## 次にやること\nBRAIN連携を確認する。\n",
        )

    def discover_candidate(self) -> dict:
        project_continuity.create_project("PETIT", project_id="petit")
        self.make_project_note()
        result = brain_project_sync.discover_project_candidates("petit")
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)
        return result["candidates"][0]

    def test_discovery_creates_candidate_but_not_source_link(self) -> None:
        self.make_project_note()
        self.write_note("_private/PETIT.md", "# Secret\nPETIT secret")
        self.write_note("Projects/PETIT.txt", "not markdown")
        project_continuity.create_project("PETIT", project_id="petit")

        result = brain_project_sync.discover_project_candidates("petit")

        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["relative_path"], "Projects/PETIT.md")
        self.assertEqual(candidate["status"], "pending")
        with db.get_connection() as conn:
            links = conn.execute(
                "SELECT COUNT(*) FROM project_source_links WHERE provider='brain'"
            ).fetchone()[0]
        self.assertEqual(links, 0)

    def test_explicit_inspection_rejects_private_outside_and_non_markdown(self) -> None:
        self.write_note("_private/Secret.md", "secret")
        outside = Path(self.temp_dir.name) / "outside.md"
        outside.write_text("outside", encoding="utf-8")
        self.write_note("Projects/PETIT.txt", "text")

        private = brain_project_sync.inspect_note("_private/Secret.md")
        traversal = brain_project_sync.inspect_note("../outside.md")
        non_markdown = brain_project_sync.inspect_note("Projects/PETIT.txt")

        self.assertFalse(private["ok"])
        self.assertFalse(traversal["ok"])
        self.assertFalse(non_markdown["ok"])

    def test_link_requires_confirmation_and_builds_bounded_cache(self) -> None:
        candidate = self.discover_candidate()

        linked = brain_project_sync.link_candidate(int(candidate["id"]), "petit")

        self.assertTrue(linked["linked"])
        self.assertIsNotNone(linked["source_link"]["confirmed_at"])
        self.assertEqual(linked["candidate"]["status"], "linked")
        notes = brain_project_sync.project_notes("petit")
        self.assertEqual(len(notes), 1)
        self.assertLessEqual(len(notes[0]["excerpt"]), 1200)
        self.assertIn("PETIT", notes[0]["title"])
        self.assertIn("discover_brain_project_candidates", registered_names())
        self.assertTrue(requires_confirmation("link_brain_note_candidate"))
        self.assertTrue(requires_confirmation("ignore_brain_note_candidate"))

    def test_content_change_creates_one_idempotent_event(self) -> None:
        candidate = self.discover_candidate()
        brain_project_sync.link_candidate(int(candidate["id"]), "petit")
        path = self.root / "Projects/PETIT.md"
        path.write_text(
            "# PETIT\n\n設計方針を更新した。\n\n## 次にやること\n実ブラウザで確認する。\n",
            encoding="utf-8",
        )
        vault_indexer._TEXT_CACHE.pop(str(path), None)

        first = brain_project_sync.refresh_note_link(
            "petit", str(candidate["external_id"]), force=True
        )
        second = brain_project_sync.refresh_note_link(
            "petit", str(candidate["external_id"]), force=True
        )

        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])
        with db.get_connection() as conn:
            events = conn.execute(
                "SELECT event_type, summary FROM project_events WHERE provider='brain'"
            ).fetchall()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "brain_note_updated")

    def test_source_refresh_reads_only_confirmed_target_note(self) -> None:
        project_continuity.create_project("PETIT", project_id="petit")
        project_continuity.create_project("Other", project_id="other")
        project_continuity.link_project_source(
            "petit", "brain", "vault:0:Projects/PETIT.md", confirmed=True
        )
        project_continuity.link_project_source(
            "petit", "brain", "vault:0:Projects/Unconfirmed.md"
        )
        removed = project_continuity.link_project_source(
            "petit", "brain", "vault:0:Projects/Removed.md", confirmed=True
        )
        project_continuity.remove_project_source_link(removed["id"])
        project_continuity.link_project_source(
            "other", "brain", "vault:0:Projects/Other.md", confirmed=True
        )
        calls: list[tuple[str, str, bool]] = []

        result = project_source_refresh.refresh_project_sources(
            "petit",
            force=True,
            brain_refresher=lambda project_id, external_id, *, force: calls.append(
                (project_id, external_id, force)
            )
            or {
                "ok": True,
                "configured": True,
                "skipped": False,
                "stale": False,
                "external_id": external_id,
            },
        )

        self.assertTrue(result["ok"])
        self.assertEqual(calls, [("petit", "vault:0:Projects/PETIT.md", True)])
        self.assertEqual(result["attempted"], ["brain"])
        self.assertEqual(result["confirmed_link_count"], 1)

    def test_missing_note_keeps_cache_and_checkpoint_for_resume(self) -> None:
        candidate = self.discover_candidate()
        brain_project_sync.link_candidate(int(candidate["id"]), "petit")
        project_continuity.save_project_checkpoint(
            "soso",
            "petit",
            stage="implemented",
            last_summary="BRAIN連携を実装",
            next_action="実画面で確認",
        )
        (self.root / "Projects/PETIT.md").unlink()
        vault_indexer._TEXT_CACHE.clear()

        failed = brain_project_sync.refresh_note_link(
            "petit", str(candidate["external_id"]), force=True
        )
        context = project_resume.build_resume_context("soso", "petit")
        rendered = project_resume.render_resume_message(context)

        self.assertFalse(failed["ok"])
        self.assertTrue(failed["cached"])
        self.assertTrue(failed["stale"])
        self.assertEqual(context.checkpoint["last_summary"], "BRAIN連携を実装")
        self.assertEqual(len(context.brain_notes), 1)
        self.assertIn("関連BRAIN", rendered)
        self.assertIn("brainは最新同期に失敗", rendered)
        self.assertIn("実画面で確認", rendered)

    def test_resume_excerpt_is_bounded(self) -> None:
        project_continuity.create_project("PETIT", project_id="petit")
        self.write_note("Projects/PETIT.md", "# PETIT\n\n" + ("長い本文" * 1000))
        inspected = brain_project_sync.inspect_note(
            "Projects/PETIT.md", project_id="petit"
        )
        brain_project_sync.link_candidate(int(inspected["candidate"]["id"]), "petit")

        context = project_resume.build_resume_context("soso", "petit")
        rendered = project_resume.render_resume_message(context)

        self.assertLessEqual(len(context.brain_notes[0]["excerpt"]), 1200)
        self.assertLess(len(rendered), 1000)
        self.assertEqual(context.reference_counts()["brain_notes"], 1)


if __name__ == "__main__":
    unittest.main()
