from __future__ import annotations

import unittest
from unittest.mock import patch

from backend import github_client, github_config


class GitHubClientEvidenceTests(unittest.TestCase):
    def test_check_runs_recheck_default_branch_and_deduplicate(self) -> None:
        calls: list[str] = []

        def fake_get(path: str, params=None, timeout: float = 20):
            calls.append(path)
            if path.endswith("/commits/abc123/check-runs"):
                return {
                    "check_runs": [
                        {"id": 1, "name": "tests", "head_sha": "abc123", "status": "in_progress"}
                    ]
                }
            if path.endswith("/commits/main/check-runs"):
                return {
                    "check_runs": [
                        {"id": 1, "name": "tests", "head_sha": "abc123", "status": "completed", "conclusion": "success"}
                    ]
                }
            raise AssertionError(path)

        with patch.object(github_client, "_get", side_effect=fake_get):
            checks = github_client.list_check_runs("Soso2e/PETIT", ["abc123", "main"])

        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0]["conclusion"], "success")
        self.assertEqual(
            calls,
            [
                "/repos/Soso2e/PETIT/commits/abc123/check-runs",
                "/repos/Soso2e/PETIT/commits/main/check-runs",
            ],
        )

    def test_deployment_status_after_cursor_is_included(self) -> None:
        def fake_get(path: str, params=None, timeout: float = 20):
            if path.endswith("/deployments"):
                return [
                    {
                        "id": 10,
                        "environment": "production",
                        "created_at": "2026-07-17T00:00:00Z",
                        "updated_at": "2026-07-17T00:00:00Z",
                    }
                ]
            if path.endswith("/deployments/10/statuses"):
                return [
                    {
                        "id": 101,
                        "state": "success",
                        "created_at": "2026-07-18T06:00:00Z",
                        "updated_at": "2026-07-18T06:00:00Z",
                    }
                ]
            raise AssertionError(path)

        with patch.object(github_client, "_get", side_effect=fake_get), patch.object(
            github_config, "MAX_DEPLOYMENTS", 20
        ):
            deployments = github_client.list_deployments(
                "Soso2e/PETIT", since="2026-07-18T05:00:00Z"
            )

        self.assertEqual(len(deployments), 1)
        self.assertEqual(deployments[0]["latest_status"]["state"], "success")

    def test_old_deployment_and_old_status_are_excluded(self) -> None:
        def fake_get(path: str, params=None, timeout: float = 20):
            if path.endswith("/deployments"):
                return [{"id": 10, "created_at": "2026-07-17T00:00:00Z"}]
            if path.endswith("/deployments/10/statuses"):
                return [{"id": 101, "state": "success", "updated_at": "2026-07-17T01:00:00Z"}]
            raise AssertionError(path)

        with patch.object(github_client, "_get", side_effect=fake_get):
            deployments = github_client.list_deployments(
                "Soso2e/PETIT", since="2026-07-18T05:00:00Z"
            )

        self.assertEqual(deployments, [])


if __name__ == "__main__":
    unittest.main()
