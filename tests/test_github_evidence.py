from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import (
    config,
    db,
    github_config,
    github_project_links,
    github_sync,
    project_continuity,
    project_source_refresh,
)
from backend.github_client import normalize_repository
from backend.tools.registry import registered_names, requires_confirmation


class GitHubEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(config, "DB_PATH", Path(self.temp_dir.name) / "app.db")
        self.db_patch.start()
        db.init_db()
        project_continuity.ensure_project_schema()
        github_sync.ensure_github_schema()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    @staticmethod
    def repository(full_name: str = "Soso2e/PETIT") -> dict:
        owner, name = full_name.split("/", 1)
        return {
            "id": 123,
            "name": name,
            "full_name": full_name,
            "owner": {"login": owner},
            "default_branch": "main",
            "private": True,
            "visibility": "private",
            "description": "Personal assistant",
            "html_url": f"https://github.com/{full_name}",
            "pushed_at": "2026-07-18T05:30:00Z",
            "updated_at": "2026-07-18T05:30:00Z",
        }

    @classmethod
    def snapshot(cls, full_name: str = "Soso2e/PETIT") -> dict:
        return {
            "source": "github",
            "repository": cls.repository(full_name),
            "since": None,
            "nextSince": "2026-07-18T05:40:00+00:00",
            "commits": [
                {
                    "sha": "abcdef1234567890",
                    "html_url": f"https://github.com/{full_name}/commit/abcdef1",
                    "commit": {
                        "message": "Implement evidence adapter\n\nDetails",
                        "author": {"name": "Soso", "date": "2026-07-18T05:10:00Z"},
                        "committer": {"name": "Soso", "date": "2026-07-18T05:11:00Z"},
                    },
                }
            ],
            "pullRequests": [
                {
                    "number": 28,
                    "title": "feat: GitHub evidence",
                    "state": "closed",
                    "draft": False,
                    "created_at": "2026-07-18T05:00:00Z",
                    "updated_at": "2026-07-18T05:20:00Z",
                    "closed_at": "2026-07-18T05:20:00Z",
                    "merged_at": "2026-07-18T05:20:00Z",
                    "html_url": f"https://github.com/{full_name}/pull/28",
                    "head": {"ref": "feat/github-evidence", "sha": "abcdef1234567890"},
                    "base": {"ref": "main"},
                }
            ],
            "checkRuns": [
                {
                    "id": 10,
                    "name": "unit tests",
                    "status": "completed",
                    "conclusion": "success",
                    "commit_sha": "abcdef1234567890",
                    "started_at": "2026-07-18T05:12:00Z",
                    "completed_at": "2026-07-18T05:14:00Z",
                    "html_url": f"https://github.com/{full_name}/actions/runs/10",
                },
                {
                    "id": 11,
                    "name": "browser tests",
                    "status": "completed",
                    "conclusion": "failure",
                    "commit_sha": "abcdef1234567890",
                    "started_at": "2026-07-18T05:12:00Z",
                    "completed_at": "2026-07-18T05:15:00Z",
                    "html_url": f"https://github.com/{full_name}/actions/runs/11",
                },
                {
                    "id": 12,
                    "name": "deploy preview",
                    "status": "in_progress",
                    "conclusion": None,
                    "commit_sha": "abcdef1234567890",
                    "started_at": "2026-07-18T05:16:00Z",
                    "completed_at": None,
                    "html_url": f"https://github.com/{full_name}/actions/runs/12",
                },
            ],
            "deployments": [
                {
                    "id": 20,
                    "environment": "production",
                    "ref": "main",
                    "sha": "abcdef1234567890",
                    "created_at": "2026-07-18T05:21:00Z",
                    "updated_at": "2026-07-18T05:22:00Z",
                    "latest_status": {
                        "id": 201,
                        "state": "success",
                        "created_at": "2026-07-18T05:22:00Z",
                        "updated_at": "2026-07-18T05:22:00Z",
                        "environment_url": "https://petit.example",
                    },
                },
                {
                    "id": 21,
                    "environment": "preview",
                    "ref": "feat/github-evidence",
                    "sha": "abcdef1234567890",
                    "created_at": "2026-07-18T05:23:00Z",
                    "updated_at": "2026-07-18T05:24:00Z",
                    "latest_status": {
                        "id": 211,
                        "state": "failure",
                        "created_at": "2026-07-18T05:24:00Z",
                        "updated_at": "2026-07-18T05:24:00Z",
                        "log_url": "https://github.com/example/log",
                    },
                },
            ],
        }

    def test_repository_inspection_creates_unconfirmed_candidate(self) -> None:
        project_continuity.create_project("PETIT", project_id="petit")
        result = github_sync.inspect_repository(
            "https://github.com/Soso2e/PETIT",
            repository_loader=lambda repository: self.repository(repository),
        )

        self.assertTrue(result["ok"])
        candidate = result["candidate"]
        self.assertEqual(candidate["full_name"], "Soso2e/PETIT")
        self.assertEqual(candidate["status"], "pending")
        with db.get_connection() as conn:
            link_count = conn.execute(
                "SELECT COUNT(*) FROM project_source_links WHERE provider='github'"
            ).fetchone()[0]
        self.assertEqual(link_count, 0)

    def test_candidate_link_is_confirmed_and_tools_are_registered(self) -> None:
        project_continuity.create_project("PETIT", project_id="petit")
        inspected = github_sync.inspect_repository(
            "Soso2e/PETIT",
            repository_loader=lambda repository: self.repository(repository),
        )
        candidate_id = int(inspected["candidate"]["id"])

        linked = github_project_links.link_candidate(candidate_id, "petit")

        self.assertTrue(linked["linked"])
        self.assertIsNotNone(linked["source_link"]["confirmed_at"])
        self.assertEqual(linked["candidate"]["status"], "linked")
        self.assertIn("inspect_github_repository", registered_names())
        self.assertIn("sync_github_evidence", registered_names())
        self.assertTrue(requires_confirmation("link_github_repository_candidate"))
        self.assertTrue(requires_confirmation("ignore_github_repository_candidate"))

    def test_snapshot_keeps_evidence_types_distinct_and_idempotent(self) -> None:
        project_continuity.create_project("PETIT", project_id="petit")
        project_continuity.save_project_checkpoint(
            "soso",
            "petit",
            stage="implemented",
            last_summary="実装済み、検証は未完了",
            unverified_items=["実画面", "本番確認"],
        )

        first = github_sync.apply_snapshot(self.snapshot(), "petit")
        second = github_sync.apply_snapshot(self.snapshot(), "petit")

        self.assertEqual(first["counts"], second["counts"])
        with db.get_connection() as conn:
            evidence = conn.execute(
                "SELECT evidence_type, state, COUNT(*) AS count FROM github_evidence_cache "
                "GROUP BY evidence_type, state ORDER BY evidence_type, state"
            ).fetchall()
            events = conn.execute(
                "SELECT event_type FROM project_events WHERE provider='github' ORDER BY event_type"
            ).fetchall()
        self.assertEqual(sum(int(row["count"]) for row in evidence), 7)
        self.assertEqual(
            [row["event_type"] for row in events],
            [
                "check_failed",
                "check_succeeded",
                "commit_pushed",
                "deployment_failed",
                "deployment_succeeded",
                "pull_request_merged",
            ],
        )
        checkpoint = project_continuity.get_project_checkpoint("soso", "petit")
        self.assertEqual(checkpoint["stage"], "implemented")
        self.assertEqual(checkpoint["unverified_items"], ["実画面", "本番確認"])

    def test_resume_refresh_reads_only_confirmed_target_repository(self) -> None:
        project_continuity.create_project("PETIT", project_id="petit")
        project_continuity.create_project("Other", project_id="other")
        project_continuity.link_project_source("petit", "github", "Soso2e/PETIT", confirmed=True)
        project_continuity.link_project_source("petit", "github", "Soso2e/Unconfirmed")
        removed = project_continuity.link_project_source("petit", "github", "Soso2e/Removed", confirmed=True)
        project_continuity.remove_project_source_link(removed["id"])
        project_continuity.link_project_source("other", "github", "Soso2e/Other", confirmed=True)
        calls: list[tuple[str, str, bool]] = []

        result = project_source_refresh.refresh_project_sources(
            "petit",
            force=True,
            github_refresher=lambda project_id, repository, *, force: calls.append(
                (project_id, repository, force)
            )
            or {
                "ok": True,
                "configured": True,
                "skipped": False,
                "stale": False,
                "repository": repository,
            },
        )

        self.assertTrue(result["ok"])
        self.assertEqual(calls, [("petit", "Soso2e/PETIT", True)])
        self.assertEqual(result["attempted"], ["github"])
        self.assertEqual(result["confirmed_link_count"], 1)

    def test_cursor_ttl_and_failure_preserve_cache_and_redact_token(self) -> None:
        project_continuity.create_project("PETIT", project_id="petit")
        project_continuity.link_project_source("petit", "github", "Soso2e/PETIT", confirmed=True)
        calls: list[tuple[str, str | None]] = []

        with patch.multiple(
            github_config,
            TOKEN="secret-read-token",
            SYNC_TTL_SECONDS=300.0,
        ):
            first = github_sync.refresh_repository_link(
                "petit",
                "Soso2e/PETIT",
                force=True,
                snapshot_loader=lambda repository, since: calls.append((repository, since))
                or self.snapshot(repository),
            )
            second = github_sync.refresh_repository_link(
                "petit",
                "Soso2e/PETIT",
                force=False,
                snapshot_loader=lambda repository, since: calls.append((repository, since))
                or self.snapshot(repository),
            )

            def fail(repository: str, since: str | None) -> dict:
                raise RuntimeError("secret-read-token must not leak")

            failed = github_sync.refresh_repository_link(
                "petit",
                "Soso2e/PETIT",
                force=True,
                snapshot_loader=fail,
            )

        self.assertTrue(first["ok"])
        self.assertTrue(second["cached"])
        self.assertEqual(calls, [("Soso2e/PETIT", None)])
        self.assertFalse(failed["ok"])
        self.assertTrue(failed["cached"])
        self.assertTrue(failed["stale"])
        self.assertNotIn("secret-read-token", failed["error"])
        self.assertIn("[redacted]", failed["error"])
        self.assertEqual(github_sync.cursor("Soso2e/PETIT"), "2026-07-18T05:40:00+00:00")

    def test_repository_normalization_accepts_url_and_rejects_invalid(self) -> None:
        self.assertEqual(normalize_repository("https://github.com/Soso2e/PETIT.git"), "Soso2e/PETIT")
        with self.assertRaisesRegex(Exception, "owner/name"):
            normalize_repository("not a repository")


if __name__ == "__main__":
    unittest.main()
