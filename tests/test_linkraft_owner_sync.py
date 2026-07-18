from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import (
    config,
    db,
    linkraft_config,
    linkraft_project_links,
    linkraft_sync,
    project_continuity,
    project_resume,
    tools,
)
from backend.linkraft_client import LinkraftError


class LinkraftOwnerSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(config, "DB_PATH", Path(self.temp_dir.name) / "app.db")
        self.db_patch.start()
        self.linkraft_patch = patch.multiple(
            linkraft_config,
            BASE_URL="https://linkraft.example",
            READ_TOKEN="test-token",
            SYNC_TTL_SECONDS=300.0,
        )
        self.linkraft_patch.start()
        db.init_db()
        project_continuity.ensure_project_schema()
        linkraft_sync.ensure_linkraft_schema()
        linkraft_sync._last_sync_monotonic.clear()

    def tearDown(self) -> None:
        self.linkraft_patch.stop()
        self.db_patch.stop()
        self.temp_dir.cleanup()

    @staticmethod
    def project(external_id: str = "linkraft-petit", name: str = "PETIT") -> dict:
        return {
            "id": external_id,
            "groupId": "group-a",
            "name": name,
            "description": "個人AIアシスタント",
            "goal": "制作を継続する",
            "color": "orange",
            "visibility": "group",
            "mentorId": None,
            "mentorRequestStatus": "none",
            "deletionStatus": "active",
            "createdAt": "2026-07-01T00:00:00.000Z",
            "updatedAt": "2026-07-18T01:00:00.000Z",
        }

    @staticmethod
    def snapshot(external_id: str = "linkraft-petit", *, full: bool = True, next_since: str = "2026-07-18T02:00:00.000Z") -> dict:
        return {
            "source": "linkraft",
            "fullSnapshot": full,
            "since": None if full else "2026-07-18T01:00:00.000Z",
            "nextSince": next_since,
            "project": LinkraftOwnerSyncTests.project(external_id),
            "tasks": [
                {
                    "id": "task-a",
                    "projectId": external_id,
                    "title": "PETIT read APIを確認",
                    "status": "やっている",
                    "assigneeId": "owner-user",
                    "due": "2026-07-20",
                    "createdBy": "owner-user",
                    "createdAt": "2026-07-18T00:00:00.000Z",
                    "updatedAt": "2026-07-18T01:10:00.000Z",
                }
            ],
            "activities": [
                {
                    "id": "activity-a",
                    "projectId": external_id,
                    "actorId": "owner-user",
                    "type": "task_updated",
                    "text": "そそさんがタスクをやっているにしました",
                    "createdAt": "2026-07-18T01:11:00.000Z",
                    "updatedAt": "2026-07-18T01:11:00.000Z",
                }
            ],
            "supportPosts": [
                {
                    "id": "support-a",
                    "projectId": external_id,
                    "taskId": "task-a",
                    "authorId": "owner-user",
                    "kind": "stuck",
                    "body": "公開環境の確認で止まっている",
                    "helpStatus": "supporting",
                    "assignedSupporterId": "mentor-user",
                    "nextAction": "公開D1を確認する",
                    "resolutionSummary": None,
                    "createdAt": "2026-07-18T01:12:00.000Z",
                    "updatedAt": "2026-07-18T01:12:00.000Z",
                }
            ],
            "knowledge": [
                {
                    "id": "knowledge-a",
                    "projectId": external_id,
                    "title": "公開確認手順",
                    "type": "メモ",
                    "description": "D1 migration後に2アカウント確認",
                    "url": "https://example.invalid/knowledge",
                    "createdBy": "owner-user",
                    "createdAt": "2026-07-18T01:13:00.000Z",
                    "updatedAt": "2026-07-18T01:13:00.000Z",
                }
            ],
        }

    def test_owned_project_list_creates_candidate_without_snapshot_or_auto_link(self) -> None:
        snapshot_calls: list[tuple[str, str | None]] = []

        result = linkraft_sync.sync_if_configured(
            force=True,
            project_loader=lambda: [self.project()],
            snapshot_loader=lambda project_id, since: snapshot_calls.append((project_id, since)) or self.snapshot(project_id),
        )

        self.assertTrue(result["ok"])
        self.assertEqual(snapshot_calls, [])
        candidates = linkraft_project_links.list_candidates()
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["external_id"], "linkraft-petit")
        self.assertIsNone(candidates[0]["project_id"])
        self.assertEqual(candidates[0]["status"], "pending")
        with db.get_connection() as conn:
            tasks = conn.execute("SELECT COUNT(*) FROM tasks_cache WHERE source='linkraft'").fetchone()[0]
        self.assertEqual(tasks, 0)

    def test_confirmed_candidate_enables_snapshot_sync_and_normalized_events(self) -> None:
        project_continuity.create_project("PETIT", project_id="petit")
        linkraft_sync.sync_if_configured(
            force=True,
            project_loader=lambda: [self.project()],
            snapshot_loader=lambda project_id, since: self.snapshot(project_id),
        )
        candidate = linkraft_project_links.list_candidates()[0]
        self.assertTrue(tools.requires_confirmation("link_linkraft_project_candidate"))
        linked = json.loads(
            tools.dispatch(
                "link_linkraft_project_candidate",
                {"candidate_id": candidate["id"], "project_id": "petit"},
            )
        )
        self.assertTrue(linked["linked"])
        self.assertIsNotNone(linked["source_link"]["confirmed_at"])

        calls: list[tuple[str, str | None]] = []
        result = linkraft_sync.sync_if_configured(
            force=True,
            project_loader=lambda: [self.project()],
            snapshot_loader=lambda project_id, since: calls.append((project_id, since)) or self.snapshot(project_id),
        )

        self.assertTrue(result["ok"])
        self.assertEqual(calls, [("linkraft-petit", None)])
        with db.get_connection() as conn:
            task = conn.execute(
                "SELECT project_id, project_external_id, status, assignee_external_ids FROM tasks_cache "
                "WHERE source='linkraft' AND external_id='task-a'"
            ).fetchone()
            activity_count = conn.execute("SELECT COUNT(*) FROM linkraft_activity_cache").fetchone()[0]
            support = conn.execute("SELECT next_action, help_status FROM linkraft_support_cache WHERE external_id='support-a'").fetchone()
            knowledge_count = conn.execute("SELECT COUNT(*) FROM linkraft_knowledge_cache").fetchone()[0]
            events = conn.execute("SELECT provider, event_type, summary FROM project_events WHERE project_id='petit'").fetchall()
            cursor = conn.execute("SELECT next_since FROM linkraft_sync_cursors WHERE external_project_id='linkraft-petit'").fetchone()
        self.assertEqual(task["project_id"], "petit")
        self.assertEqual(task["project_external_id"], "linkraft-petit")
        self.assertEqual(task["status"], "やっている")
        self.assertEqual(json.loads(task["assignee_external_ids"]), ["owner-user"])
        self.assertEqual(activity_count, 1)
        self.assertEqual(support["next_action"], "公開D1を確認する")
        self.assertEqual(support["help_status"], "supporting")
        self.assertEqual(knowledge_count, 1)
        self.assertTrue(all(row["provider"] == "linkraft" for row in events))
        self.assertTrue(any("公開D1を確認する" in row["summary"] for row in events))
        self.assertEqual(cursor["next_since"], "2026-07-18T02:00:00.000Z")

    def test_repeated_snapshot_is_idempotent_and_uses_saved_cursor(self) -> None:
        project_continuity.create_project("PETIT", project_id="petit")
        project_continuity.link_project_source("petit", "linkraft", "linkraft-petit", confirmed=True)
        calls: list[str | None] = []

        for _ in range(2):
            linkraft_sync.sync_if_configured(
                force=True,
                project_loader=lambda: [self.project()],
                snapshot_loader=lambda project_id, since: calls.append(since) or self.snapshot(project_id, full=since is None),
            )

        self.assertEqual(calls, [None, "2026-07-18T02:00:00.000Z"])
        with db.get_connection() as conn:
            event_count = conn.execute("SELECT COUNT(*) FROM project_events WHERE provider='linkraft'").fetchone()[0]
            task_count = conn.execute("SELECT COUNT(*) FROM tasks_cache WHERE source='linkraft'").fetchone()[0]
        self.assertEqual(event_count, 4)
        self.assertEqual(task_count, 1)

    def test_full_snapshot_removes_missing_linkraft_tasks_only(self) -> None:
        project_continuity.create_project("PETIT", project_id="petit")
        project_continuity.link_project_source("petit", "linkraft", "linkraft-petit", confirmed=True)
        linkraft_sync.apply_snapshot(self.snapshot(), "petit")
        with db.get_connection() as conn:
            conn.execute(
                "INSERT INTO tasks_cache (source, title, status, external_id, updated_at) VALUES ('local', 'Local task', 'todo', 'local-a', ?)",
                (db.now_iso(),),
            )
        empty = self.snapshot()
        empty["tasks"] = []
        linkraft_sync.apply_snapshot(empty, "petit")

        with db.get_connection() as conn:
            linkraft_count = conn.execute("SELECT COUNT(*) FROM tasks_cache WHERE source='linkraft'").fetchone()[0]
            local_count = conn.execute("SELECT COUNT(*) FROM tasks_cache WHERE source='local'").fetchone()[0]
        self.assertEqual(linkraft_count, 0)
        self.assertEqual(local_count, 1)

    def test_project_snapshot_failure_keeps_cache_and_reports_stale(self) -> None:
        project_continuity.create_project("PETIT", project_id="petit")
        project_continuity.link_project_source("petit", "linkraft", "linkraft-petit", confirmed=True)
        first = linkraft_sync.sync_if_configured(
            force=True,
            project_loader=lambda: [self.project()],
            snapshot_loader=lambda project_id, since: self.snapshot(project_id),
        )
        self.assertTrue(first["ok"])

        def fail_snapshot(project_id: str, since: str | None) -> dict:
            raise LinkraftError("snapshot unavailable")

        second = linkraft_sync.sync_if_configured(
            force=True,
            project_loader=lambda: [self.project()],
            snapshot_loader=fail_snapshot,
        )

        self.assertFalse(second["ok"])
        self.assertTrue(second["stale"])
        with db.get_connection() as conn:
            task_count = conn.execute("SELECT COUNT(*) FROM tasks_cache WHERE source='linkraft'").fetchone()[0]
        self.assertEqual(task_count, 1)

    def test_resume_discloses_stale_linkraft_project_source(self) -> None:
        project_continuity.create_project("PETIT", project_id="petit")
        project_continuity.link_project_source("petit", "linkraft", "linkraft-petit", confirmed=True)
        db.record_sync_success("linkraft:projects", 1)
        db.record_sync_success("linkraft:project:linkraft-petit", 4)
        db.record_sync_failure("linkraft:project:linkraft-petit", "timeout")

        context = project_resume.build_resume_context("soso", "petit")
        rendered = project_resume.render_resume_message(context)

        self.assertTrue(context.source_freshness["linkraft"]["stale"])
        self.assertIn("linkraftは最新同期に失敗", rendered)

    def test_error_text_redacts_read_token(self) -> None:
        error = linkraft_sync._safe_error(LinkraftError("request test-token failed"))
        self.assertNotIn("test-token", error)
        self.assertIn("[redacted]", error)


if __name__ == "__main__":
    unittest.main()
