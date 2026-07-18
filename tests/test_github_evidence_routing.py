from __future__ import annotations

import unittest

from backend import agent


class GitHubEvidenceRoutingTests(unittest.TestCase):
    def test_repository_url_registration_exposes_only_inspection(self) -> None:
        names = agent._related_tool_names(
            "https://github.com/Soso2e/PETIT をプロジェクトに紐付けたい"
        )
        self.assertEqual(names, ["inspect_github_repository"])

    def test_explicit_sync_exposes_github_sync(self) -> None:
        self.assertEqual(
            agent._related_tool_names("GitHubの進捗を同期して"),
            ["sync_github_evidence"],
        )

    def test_candidate_actions_are_narrowly_routed(self) -> None:
        self.assertEqual(
            agent._related_tool_names("GitHubリポジトリ候補を紐付けたい"),
            ["link_github_repository_candidate"],
        )
        self.assertEqual(
            agent._related_tool_names("GitHubリポジトリ候補を無視して"),
            ["ignore_github_repository_candidate"],
        )

    def test_general_github_chat_stays_tool_free(self) -> None:
        self.assertEqual(agent._related_tool_names("GitHubって便利だよね"), [])


if __name__ == "__main__":
    unittest.main()
