from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import config, db, project_continuity, project_resume, project_source_refresh


class ProjectSourceRefreshTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(config, "DB_PATH", Path(self.temp_dir.name) / "app.db")
        self.db_patch.start()
        db.init_db()
        project_continuity.ensure_project_schema()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    @staticmethod
    def success(project_id: str, external_id: str, *, force: bool) -> dict:
        return {"ok": True, "configured": True, "skipped": False,
                "stale": False, "external_id": external_id}

    def test_only_confirmed_sources_refresh_and_legacy_linkraft_is_skipped(self) -> None:
        project_continuity.create_project("PETIT", project_id="petit")
        project_continuity.create_project("Other", project_id="other")
        project_continuity.link_project_source("petit", "notion", "notion-petit", confirmed=True)
        project_continuity.link_project_source("petit", "github", "Soso2e/PETIT", confirmed=True)
        project_continuity.link_project_source("petit", "brain", "notes/petit.md", confirmed=True)
        project_continuity.link_project_source("petit", "linkraft", "legacy-link", confirmed=True)
        project_continuity.link_project_source("petit", "github", "unconfirmed")
        project_continuity.link_project_source("other", "github", "Soso2e/OTHER", confirmed=True)
        removed = project_continuity.link_project_source("petit", "notion", "removed", confirmed=True)
        project_continuity.remove_project_source_link(removed["id"])

        calls = []
        def observed(provider):
            def refresh(project_id, external_id, *, force):
                calls.append((provider, project_id, external_id, force))
                return self.success(project_id, external_id, force=force)
            return refresh

        result = project_source_refresh.refresh_project_sources(
            "petit", force=True,
            notion_refresher=lambda *, force: {"ok": True, "configured": True,
                                                "skipped": False, "stale": False},
            github_refresher=observed("github"),
            brain_refresher=observed("brain"),
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["attempted"], ["brain", "github", "notion"])
        self.assertEqual(result["skipped"], ["linkraft"])
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["confirmed_link_count"], 4)
        self.assertEqual(calls, [("brain", "petit", "notes/petit.md", True),
                                 ("github", "petit", "Soso2e/PETIT", True)])
        self.assertEqual(result["providers"]["linkraft"]["error"], "unsupported provider")
        with db.get_connection() as conn:
            links = conn.execute(
                "SELECT COUNT(*) FROM project_source_links "
                "WHERE provider='linkraft' AND external_id='legacy-link' AND status='active'"
            ).fetchone()[0]
        self.assertEqual(links, 1)

    def test_unconfigured_notion_is_skipped_without_failure(self) -> None:
        project_continuity.create_project("PETIT", project_id="petit")
        project_continuity.link_project_source("petit", "notion", "notion-petit", confirmed=True)
        result = project_source_refresh.refresh_project_sources(
            "petit", notion_refresher=lambda *, force: {
                "ok": False, "configured": False, "skipped": True,
                "stale": False, "error": "未設定",
            },
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["attempted"], [])
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["skipped"], ["notion"])

    def test_resume_preserves_checkpoint_when_supported_source_fails(self) -> None:
        project_continuity.create_project("PETIT", project_id="petit")
        project_continuity.save_project_checkpoint(
            "soso", "petit", stage="automated_tests_verified",
            last_summary="自動テストまで完了", next_action="実ブラウザで確認する",
        )
        failure = {"ok": False, "project_id": "petit",
                   "providers": {"github": {"ok": False, "error": "timeout"}},
                   "attempted": ["github"], "failed": ["github"], "skipped": []}
        with patch.object(project_source_refresh, "refresh_project_sources", return_value=failure):
            context = project_resume.build_resume_context("soso", "petit")
        rendered = project_resume.render_resume_message(context)
        self.assertEqual(context.checkpoint["last_summary"], "自動テストまで完了")
        self.assertIn("自動テストまで完了", rendered)
        self.assertIn("実ブラウザで確認する", rendered)
        self.assertIn("githubの更新に失敗", rendered)
        self.assertEqual(context.reference_counts()["source_refresh_failed"], ["github"])

    def test_failed_supported_source_does_not_block_other_sources(self) -> None:
        project_continuity.create_project("PETIT", project_id="petit")
        project_continuity.link_project_source("petit", "github", "Soso2e/PETIT", confirmed=True)
        project_continuity.link_project_source("petit", "notion", "notion-petit", confirmed=True)
        result = project_source_refresh.refresh_project_sources(
            "petit",
            github_refresher=lambda *args, **kwargs: {
                "ok": False, "configured": True, "skipped": False,
                "stale": True, "error": "timeout"},
            notion_refresher=lambda *, force: {
                "ok": True, "configured": True, "skipped": False, "stale": False},
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["failed"], ["github"])
        self.assertEqual(result["attempted"], ["github", "notion"])
        self.assertTrue(result["providers"]["notion"]["ok"])


if __name__ == "__main__":
    unittest.main()
