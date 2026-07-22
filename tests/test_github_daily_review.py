from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from backend import agent, config, db, github_config, github_daily_review, tools
from backend.tools.registry import registered_names, requires_confirmation


class GitHubDailyReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(config, "DB_PATH", Path(self.temp_dir.name) / "app.db")
        self.db_patch.start()
        db.init_db()
        github_daily_review.ensure_schema()
        self.common_patches = patch.multiple(
            github_daily_review,
            REVIEW_ENABLED=True,
            REVIEW_LOOKBACK_HOURS=24,
            REVIEW_MAX_REPOSITORIES=50,
            REVIEW_MAX_COMMITS_PER_REPO=10,
            REVIEW_PROGRESS_MAX_CHARS=1800,
            REVIEW_INCLUDE_FORKS=False,
        )
        self.common_patches.start()
        self.token_patch = patch.object(github_config, "TOKEN", "secret-token")
        self.token_patch.start()
        self.message_patch = patch.object(
            github_daily_review,
            "_generate_message",
            side_effect=lambda repositories, **kwargs: (
                github_daily_review._fallback_message(repositories, **kwargs),
                "template",
            ),
        )
        self.message_patch.start()

    def tearDown(self) -> None:
        self.message_patch.stop()
        self.token_patch.stop()
        self.common_patches.stop()
        self.db_patch.stop()
        self.temp_dir.cleanup()

    @staticmethod
    def repository(full_name: str, **overrides):
        owner, name = full_name.split("/", 1)
        data = {
            "id": hash(full_name) & 0xFFFF,
            "name": name,
            "full_name": full_name,
            "owner": {"login": owner},
            "default_branch": "main",
            "private": True,
            "visibility": "private",
            "archived": False,
            "disabled": False,
            "fork": False,
            "size": 10,
            "pushed_at": "2026-07-22T00:30:00Z",
            "updated_at": "2026-07-22T00:30:00Z",
            "html_url": f"https://github.com/{full_name}",
        }
        data.update(overrides)
        return data

    @staticmethod
    def activity(metadata, since, *, failed=False, changed=True):
        sha = "abcdef1234567890"
        commits = []
        checks = []
        if changed:
            commits = [
                {
                    "sha": sha,
                    "html_url": f"{metadata['html_url']}/commit/{sha}",
                    "commit": {
                        "message": "feat: review repository changes\n\ndetail",
                        "author": {"name": "Soso", "date": "2026-07-22T00:20:00Z"},
                        "committer": {"name": "Soso", "date": "2026-07-22T00:21:00Z"},
                    },
                }
            ]
            checks = [
                {
                    "name": "tests",
                    "status": "completed",
                    "conclusion": "failure" if failed else "success",
                    "head_sha": sha,
                    "completed_at": "2026-07-22T00:25:00Z",
                    "html_url": f"{metadata['html_url']}/actions/runs/1",
                }
            ]
        return {
            "repository": metadata,
            "full_name": metadata["full_name"],
            "default_branch": "main",
            "since": since,
            "commits": commits,
            "pull_requests": [],
            "check_runs": checks,
            "progress": "# PROGRESS\n\n- 次にやること: 実ブラウザ確認",
            "changed": changed,
        }

    def test_filters_archived_empty_and_fork_repositories(self) -> None:
        repositories = [
            self.repository("Soso2e/PETIT"),
            self.repository("Soso2e/Archived", archived=True),
            self.repository("Soso2e/Empty", size=0, pushed_at=None),
            self.repository("Soso2e/Fork", fork=True),
        ]
        calls = []
        now = datetime(2026, 7, 22, 0, 0, tzinfo=timezone.utc)

        result = github_daily_review.run_review(
            force=True,
            repositories_loader=lambda: repositories,
            activity_loader=lambda metadata, since: calls.append((metadata["full_name"], since))
            or self.activity(metadata, since),
            now=now,
        )

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["repository_count"], 1)
        self.assertEqual(result["changed_count"], 1)
        self.assertEqual([item[0] for item in calls], ["Soso2e/PETIT"])
        self.assertEqual(result["priority"], "normal")
        self.assertTrue(result["cursor_advanced"])
        self.assertIn("PROGRESSあり", result["message"])

    def test_failed_check_is_high_priority(self) -> None:
        repository = self.repository("Soso2e/PETIT")
        result = github_daily_review.run_review(
            force=True,
            repositories_loader=lambda: [repository],
            activity_loader=lambda metadata, since: self.activity(metadata, since, failed=True),
            now=datetime(2026, 7, 22, 0, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(result["priority"], "high")
        self.assertIn("失敗CI", result["next_action"])
        self.assertIn("失敗check 1件", result["message"])

    def test_partial_failure_keeps_previous_cursor(self) -> None:
        first_repo = self.repository("Soso2e/PETIT")
        first = github_daily_review.run_review(
            force=True,
            repositories_loader=lambda: [first_repo],
            activity_loader=lambda metadata, since: self.activity(metadata, since),
            now=datetime(2026, 7, 22, 0, 0, tzinfo=timezone.utc),
        )
        previous_cursor = first["next_since"]
        repositories = [first_repo, self.repository("Soso2e/Broken")]

        def loader(metadata, since):
            if metadata["full_name"].endswith("Broken"):
                raise RuntimeError("secret-token API failed")
            return self.activity(metadata, since)

        second = github_daily_review.run_review(
            force=True,
            repositories_loader=lambda: repositories,
            activity_loader=loader,
            now=datetime(2026, 7, 22, 1, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(second["status"], "partial")
        self.assertFalse(second["cursor_advanced"])
        self.assertEqual(second["next_since"], previous_cursor)
        self.assertNotIn("secret-token", second["error"])
        self.assertIn("[redacted]", second["error"])

    def test_same_day_uses_cached_review(self) -> None:
        repository = self.repository("Soso2e/PETIT")
        calls = {"repositories": 0}

        def repositories_loader():
            calls["repositories"] += 1
            return [repository]

        now = datetime(2026, 7, 22, 0, 0, tzinfo=timezone.utc)
        first = github_daily_review.run_review(
            force=True,
            repositories_loader=repositories_loader,
            activity_loader=lambda metadata, since: self.activity(metadata, since),
            now=now,
        )
        second = github_daily_review.run_review(
            force=False,
            repositories_loader=repositories_loader,
            activity_loader=lambda metadata, since: self.activity(metadata, since),
            now=datetime(2026, 7, 22, 2, 0, tzinfo=timezone.utc),
        )

        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(calls["repositories"], 1)

    def test_source_permission_error_keeps_visible_changes_and_cursor(self) -> None:
        repository = self.repository("Soso2e/PETIT")

        def loader(metadata, since):
            snapshot = self.activity(metadata, since)
            snapshot["source_errors"] = [{"source": "check_runs", "error": "checks permission denied"}]
            return snapshot

        result = github_daily_review.run_review(
            force=True,
            repositories_loader=lambda: [repository],
            activity_loader=loader,
            now=datetime(2026, 7, 22, 0, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["changed_count"], 1)
        self.assertFalse(result["cursor_advanced"])
        self.assertIn("commit 1件", result["message"])

    def test_explicit_github_review_routing_is_deterministic(self) -> None:
        self.assertTrue(agent._github_review_requested("GitHub全体の前回差分をレビューして"))
        self.assertTrue(agent._github_review_requested("GitHubの全リポジトリと新コミットを見て"))
        self.assertFalse(agent._github_review_requested("GitHub候補をPETITに紐付けて"))

    def test_tool_is_registered_and_read_only(self) -> None:
        self.assertIn("review_github_activity", registered_names())
        self.assertFalse(requires_confirmation("review_github_activity"))


if __name__ == "__main__":
    unittest.main()
