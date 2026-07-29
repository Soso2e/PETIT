from __future__ import annotations

import unittest
from pathlib import Path

from backend import tools
from backend.tools.registry import tool


ROOT = Path(__file__).resolve().parents[1]


class ToolRiskPolicyTests(unittest.TestCase):
    def test_initial_low_risk_writes_execute_without_confirmation(self) -> None:
        for name in (
            "create_task",
            "add_task",
            "add_list_item",
            "create_handoff_note",
            "save_memory",
            "ignore_github_repository_candidate",
        ):
            if name not in tools.registered_names():
                continue
            self.assertEqual(tools.risk_for(name), "low_risk_write", name)
            self.assertFalse(tools.requires_confirmation(name), name)

    def test_confirm_writes_stay_gated(self) -> None:
        for name in (
            "add_schedule",
            "update_task",
            "complete_task",
            "edit_brain_note",
            "create_list",
            "link_github_repository_candidate",
        ):
            if name not in tools.registered_names():
                continue
            self.assertEqual(tools.risk_for(name), "confirm_write", name)
            self.assertTrue(tools.requires_confirmation(name), name)

    def test_legacy_requires_confirmation_maps_to_confirm_write(self) -> None:
        name = "_test_legacy_confirm_write"

        @tool(
            name=name,
            description="test",
            parameters={"type": "object", "properties": {}},
            requires_confirmation=True,
        )
        def handler() -> dict[str, bool]:
            return {"ok": True}

        self.assertEqual(tools.risk_for(name), "confirm_write")
        self.assertTrue(tools.requires_confirmation(name))

    def test_explicit_destructive_policy_always_requires_confirmation(self) -> None:
        name = "_test_destructive_write"

        @tool(
            name=name,
            description="test",
            parameters={"type": "object", "properties": {}},
            risk="destructive",
        )
        def handler() -> dict[str, bool]:
            return {"ok": True}

        self.assertEqual(tools.risk_for(name), "destructive")
        self.assertTrue(tools.requires_confirmation(name))

    def test_conversational_pending_decisions_share_the_button_path(self) -> None:
        source = (ROOT / "frontend" / "action_confirm.js").read_text(encoding="utf-8")
        for phrase in ("うん", "はい", "お願い", "実行して", "それでいい"):
            self.assertIn(f'"{phrase}"', source)
        for phrase in ("やめる", "キャンセル", "しない", "取り消し"):
            self.assertIn(f'"{phrase}"', source)
        self.assertIn("if (!text || !pending) return;", source)
        self.assertIn("event.stopImmediatePropagation()", source)
        self.assertIn("target.click()", source)
        self.assertIn("!buttons[0].disabled && !buttons[1].disabled", source)


if __name__ == "__main__":
    unittest.main()
