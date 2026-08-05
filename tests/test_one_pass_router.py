from __future__ import annotations

import json
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from backend import agent, capability_router, time_context


def route_tool_call(
    capabilities: list[str],
    goal: str,
    confidence: float = 0.9,
) -> dict:
    return {
        "content": "",
        "tool_calls": [
            {
                "id": "route-1",
                "type": "function",
                "function": {
                    "name": "route_to_agent",
                    "arguments": json.dumps(
                        {
                            "capabilities": capabilities,
                            "goal": goal,
                            "confidence": confidence,
                        },
                        ensure_ascii=False,
                    ),
                },
            }
        ],
    }


class OnePassRouterTests(unittest.TestCase):
    def test_tool_free_turn_returns_first_model_reply(self) -> None:
        response = {"content": "お疲れさま。今日は少し休もう。", "tool_calls": []}
        with patch.object(capability_router, "chat_completion", return_value=response) as completion:
            route = capability_router.choose("疲れた", history=[])

        self.assertEqual(route["type"], "reply")
        self.assertEqual(route["reply"], response["content"])
        self.assertEqual(route["source"], "one_pass_reply")
        completion.assert_called_once()

    def test_tool_dependent_turn_routes_through_virtual_tool(self) -> None:
        fixed = datetime(2026, 8, 5, 23, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
        with patch.object(time_context, "current_datetime", return_value=fixed):
            with patch.object(
                capability_router,
                "chat_completion",
                return_value=route_tool_call(["calendar"], "今日の予定を取得して伝える"),
            ):
                route = capability_router.choose("今日の予定を教えて", history=[])

        self.assertEqual(route["type"], "agent")
        self.assertEqual(route["capabilities"], ["calendar"])
        self.assertIn("2026-08-05", route["goal"])
        self.assertEqual(route["source"], "one_pass_tool_route")

    def test_text_reply_cannot_bypass_required_tool_guard(self) -> None:
        response = {"content": "今日は予定がありません。", "tool_calls": []}
        with patch.object(capability_router, "chat_completion", return_value=response):
            route = capability_router.choose("今日の予定を教えて", history=[])

        self.assertEqual(route["type"], "agent")
        self.assertEqual(route["capabilities"], ["calendar"])
        self.assertEqual(route["source"], "forced_tool_guard")

    def test_explicit_write_reply_is_forced_to_write_capability(self) -> None:
        response = {"content": "追加しました。", "tool_calls": []}
        with patch.object(capability_router, "chat_completion", return_value=response):
            route = capability_router.choose("タスクに卒研資料を追加して", history=[])

        self.assertEqual(route["type"], "agent")
        self.assertEqual(route["capabilities"], ["lists_and_tasks"])
        self.assertEqual(route["source"], "forced_tool_guard")

    def test_router_failure_exposes_only_explicit_read_fallback(self) -> None:
        with patch.object(
            capability_router,
            "chat_completion",
            return_value={
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "route_to_agent",
                            "arguments": "not-json",
                        }
                    }
                ],
            },
        ):
            route = capability_router.choose("PETITの状況を確認して", history=[])

        self.assertEqual(route["capabilities"], ["fallback_read"])
        selected = set(capability_router.tool_names_for(route["capabilities"]))
        forbidden_writes = {
            "create_task",
            "update_task",
            "complete_task",
            "add_schedule",
            "edit_brain_note",
            "save_memory",
            "create_list",
            "add_list_item",
            "start_background_research",
        }
        self.assertTrue(selected)
        self.assertTrue(selected.isdisjoint(forbidden_writes))

    def test_truncated_direct_reply_is_continued_once(self) -> None:
        first = {
            "content": "前半です。",
            "tool_calls": [],
            "_finish_reason": "length",
        }
        second = {
            "content": "後半です。",
            "tool_calls": [],
            "_finish_reason": "stop",
        }
        with patch.object(
            capability_router,
            "chat_completion",
            side_effect=[first, second],
        ) as completion:
            route = capability_router.choose("長めに説明して", history=[])

        self.assertEqual(route["type"], "reply")
        self.assertEqual(route["reply"], "前半です。\n後半です。")
        self.assertEqual(completion.call_count, 2)
        self.assertGreaterEqual(
            completion.call_args_list[0].kwargs["max_tokens"],
            1024,
        )

    def test_dynamic_clock_is_user_side_and_system_prefix_is_stable(self) -> None:
        captured: list[list[dict[str, str]]] = []

        def fake_completion(messages, **_kwargs):
            captured.append(messages)
            return {"content": "了解。", "tool_calls": []}

        first = datetime(2026, 8, 5, 23, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
        second = datetime(2026, 8, 6, 0, 10, tzinfo=ZoneInfo("Asia/Tokyo"))
        with patch.object(capability_router, "chat_completion", side_effect=fake_completion):
            with patch.object(time_context, "current_datetime", return_value=first):
                capability_router.choose("今日の話をしよう", history=[])
            with patch.object(time_context, "current_datetime", return_value=second):
                capability_router.choose("今日の話をしよう", history=[])

        self.assertEqual(captured[0][0], captured[1][0])
        self.assertNotEqual(captured[0][-1]["content"], captured[1][-1]["content"])
        self.assertNotIn("2026-08-05", captured[0][0]["content"])
        self.assertIn("2026-08-05", captured[0][-1]["content"])

    def test_one_pass_prompt_keeps_personality_and_quality_rules(self) -> None:
        prompt = capability_router._ROUTER_SYSTEM_PROMPT
        self.assertIn("親しい大学の同級生", prompt)
        self.assertIn("率直な意見", prompt)
        self.assertIn("読み上げやすいプレーンテキスト", prompt)
        self.assertIn("推測で作らない", prompt)

    def test_agent_prompt_keeps_safety_rules_and_allows_minimal_markdown(self) -> None:
        prompt = agent.AGENT_SYSTEM_PROMPT
        self.assertIn("Tool結果にない外部事実を作らない", prompt)
        self.assertIn("確認表示と実行はRuntimeに任せる", prompt)
        self.assertIn("最小限のMarkdown", prompt)
        self.assertNotIn("Markdownは使わない", prompt)


if __name__ == "__main__":
    unittest.main()
