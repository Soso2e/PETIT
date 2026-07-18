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

    def test_date_like_slash_text_is_not_a_repository(self) -> None:
        self.assertNotIn(
            "inspect_github_repository",
            agent._related_tool_names("2026/07/18の予定を確認して"),
        )


if __name__ == "__main__":
    unittest.main()
