from __future__ import annotations

import unittest

from backend import agent


class BrainProjectRoutingTests(unittest.TestCase):
    def test_general_brain_search_stays_on_search_tool(self) -> None:
        self.assertEqual(
            agent._related_tool_names("BRAINでPETITの設計を検索して"),
            ["search_brain_notes"],
        )

    def test_candidate_discovery_is_narrow(self) -> None:
        self.assertEqual(
            agent._related_tool_names("BRAINノート候補を探して"),
            ["discover_brain_project_candidates"],
        )

    def test_candidate_list_is_narrow(self) -> None:
        self.assertEqual(
            agent._related_tool_names("BRAINノート候補を見せて"),
            ["get_brain_note_candidates"],
        )

    def test_candidate_actions_do_not_expose_search(self) -> None:
        self.assertEqual(
            agent._related_tool_names("BRAINノート候補を紐付けたい"),
            ["link_brain_note_candidate"],
        )
        self.assertEqual(
            agent._related_tool_names("BRAINノート候補を無視して"),
            ["ignore_brain_note_candidate"],
        )

    def test_explicit_markdown_path_uses_inspection_only(self) -> None:
        self.assertEqual(
            agent._related_tool_names("BRAINの「Projects/PETIT.md」を候補として確認して"),
            ["inspect_brain_note_candidate"],
        )

    def test_brain_edit_keeps_existing_edit_tool(self) -> None:
        names = agent._related_tool_names("BRAINのノートに追記して")
        self.assertIn("edit_brain_note", names)
        self.assertNotIn("link_brain_note_candidate", names)


if __name__ == "__main__":
    unittest.main()
