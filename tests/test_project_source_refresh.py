from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import (
    config,
    db,
    linkraft_config,
    linkraft_sync,
    project_continuity,
    project_resume,
    project_source_refresh,
)


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
    def snapshot(external_id: str = "linkraft-petit") -> dict:
        return {
            "source": "linkraft",
            "fullSnapshot": True,
            "since": None,
            "nextSince": "2026-07-18T05:00:00+00:00",
            "project": {"id": external_id, "name": "PETIT"},
            "tasks": [],
            "activities": [],
            "supportPosts": [],
            "knowledge": [],
        }

    def test_only_confirmed_active_target_links_are_refreshed_once_per_provider(self) -> None:
        project_continuity.create_project("PETIT", project_id="petit")
        project_continuity.create_project("Other", project_id="other")
        project_continuity.link_project_source("petit", "notion", "notion-petit", confirmed=True)
        project_continuity.link_project_source("petit", "linkraft", "linkraft-petit", confirmed=True)
        project_continuity.link_project_source("petit", "github", "Soso2e/PETIT", confirmed=True)
        project_continuity.link_project_source("petit", "linkraft", "unconfirmed-linkraft")
        removed = project_continuity.link_project_source("petit", "notion", "removed-notion", confirmed=True)
        project_continuity.remove_project_source_link(removed["id"])
        project_continuity.link_project_source("other", "linkraft", "linkraft-other", confirmed=True)

        notion_calls: list[bool] = []
        linkraft_calls: list[tuple[str, str, bool]] = []

        result = project_source_refresh.refresh_project_sources(
            "petit",
            force=True,
            notion_refresher=lambda *, force: notion_calls.append(force)
            or {"ok": True, "configured": True, "skipped": False, "stale": False},
            linkraft_refresher=lambda project_id, external_id, *, force: linkraft_calls.append(
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
        self.assertEqual(notion_calls, [True])
        self.assertEqual(linkraft_calls, [("petit", "linkraft-petit", True)])
        self.assertEqual(result["attempted"], ["linkraft", "notion"])
        self.assertEqual(result["skipped"], ["github"])
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["confirmed_link_count"], 3)

    def test_unconfigured_provider_is_skipped_without_marking_resume_failed(self) -> None:
        project_continuity.create_project("PETIT", project_id="petit")
        project_continuity.link_project_source("petit", "notion", "notion-petit", confirmed=True)

        result = project_source_refresh.refresh_project_sources(
            "petit",
            notion_refresher=lambda *, force: {
                "ok": False,
                "configured": False,
                "skipped": True,
                "stale": False,
                "error": "未設定",
            },
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["attempted"], [])
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["skipped"], ["notion"])

    def test_explicit_refresh_failure_does_not_block_cached_resume(self) -> None:
        project_continuity.create_project("PETIT", project_id="petit")
        project_continuity.link_project_source(
            "petit",
            "linkraft",
            "linkraft-petit",
            confirmed=True,
        )
        project_continuity.save_project_checkpoint(
            "soso",
            "petit",
            stage="automated_tests_verified",
            last_summary="自動テストまで完了",
            next_action="実ブラウザで確認する",
        )

        refresh = project_source_refresh.refresh_project_sources(
            "petit",
            force=True,
            linkraft_refresher=lambda project_id, external_id, *, force: {
                "ok": False,
                "configured": True,
                "skipped": False,
                "stale": False,
                "error": "timeout",
                "external_id": external_id,
            },
        )
        self.assertFalse(refresh["ok"])
        self.assertEqual(refresh["failed"], ["linkraft"])

        context = project_resume.build_resume_context("soso", "petit")
        rendered = project_resume.render_resume_message(context)

        self.assertEqual(context.checkpoint["last_summary"], "自動テストまで完了")
        self.assertIn("自動テストまで完了", rendered)
        self.assertIn("実ブラウザで確認する", rendered)
        self.assertEqual(context.source_refresh["mode"], "cached_only")
        self.assertEqual(context.reference_counts()["source_refresh_failed"], [])

    def test_linkraft_refresh_uses_saved_cursor_and_ttl(self) -> None:
        project_continuity.create_project("PETIT", project_id="petit")
        project_continuity.link_project_source("petit", "linkraft", "linkraft-petit", confirmed=True)
        calls: list[tuple[str, str | None]] = []

        with patch.multiple(
            linkraft_config,
            BASE_URL="https://linkraft.example",
            READ_TOKEN="token",
            SYNC_TTL_SECONDS=300.0,
        ):
            first = project_source_refresh.refresh_linkraft_link(
                "petit",
                "linkraft-petit",
                force=True,
                snapshot_loader=lambda external_id, since: calls.append((external_id, since))
                or self.snapshot(external_id),
            )
            second = project_source_refresh.refresh_linkraft_link(
                "petit",
                "linkraft-petit",
                force=False,
                snapshot_loader=lambda external_id, since: calls.append((external_id, since))
                or self.snapshot(external_id),
            )

        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        self.assertTrue(second["cached"])
        self.assertEqual(calls, [("linkraft-petit", None)])
        with db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT next_since FROM linkraft_sync_cursors WHERE external_project_id='linkraft-petit'"
            ).fetchone()
        self.assertEqual(cursor["next_since"], "2026-07-18T05:00:00+00:00")

    def test_linkraft_failure_preserves_previous_success_as_stale(self) -> None:
        project_continuity.create_project("PETIT", project_id="petit")
        project_continuity.link_project_source("petit", "linkraft", "linkraft-petit", confirmed=True)

        with patch.multiple(
            linkraft_config,
            BASE_URL="https://linkraft.example",
            READ_TOKEN="token",
            SYNC_TTL_SECONDS=300.0,
        ):
            project_source_refresh.refresh_linkraft_link(
                "petit",
                "linkraft-petit",
                force=True,
                snapshot_loader=lambda external_id, since: self.snapshot(external_id),
            )

            def fail(external_id: str, since: str | None) -> dict:
                raise RuntimeError("snapshot unavailable")

            failed = project_source_refresh.refresh_linkraft_link(
                "petit",
                "linkraft-petit",
                force=True,
                snapshot_loader=fail,
            )

        self.assertFalse(failed["ok"])
        self.assertTrue(failed["cached"])
        self.assertTrue(failed["stale"])
        state = db.sync_state("linkraft:project:linkraft-petit")
        self.assertIsNotNone(state["last_success_at"])
        self.assertIsNotNone(state["last_failure_at"])


if __name__ == "__main__":
    unittest.main()
