from __future__ import annotations

import unittest
from unittest.mock import patch

from backend import agent, config


class CompactChatContextTests(unittest.TestCase):
    def test_recent_history_is_bounded_by_messages_and_characters(self) -> None:
        history = []
        for index in range(6):
            history.extend(
                [
                    {"role": "user", "content": f"user-{index}-" + ("u" * 500)},
                    {"role": "assistant", "content": f"assistant-{index}-" + ("a" * 500)},
                ]
            )

        recent = agent._recent_history(history)

        self.assertLessEqual(len(recent), agent._HISTORY_MAX_MESSAGES)
        self.assertLessEqual(sum(len(item["content"]) for item in recent), agent._HISTORY_MAX_CHARS)
        self.assertEqual(recent[0]["role"], "user")
        self.assertTrue(recent[-1]["content"].endswith("a" * 100))

    def test_simple_chat_uses_compact_prompt_and_one_model_call(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_chat(messages, tools=None, temperature=None, model=None, max_tokens=None, route="chat"):
            calls.append({"messages": messages, "tools": tools, "model": model, "route": route})
            return {"role": "assistant", "content": "楽しんできてね。"}

        history = []
        for index in range(5):
            history.extend(
                [
                    {"role": "user", "content": f"過去の話題{index}"},
                    {"role": "assistant", "content": f"過去の返答{index}"},
                ]
            )

        with (
            patch.object(agent.project_router, "try_handle_project_turn", return_value=None),
            patch.object(config, "CHAT_MODEL", "chat-test"),
            patch.object(agent, "chat_completion", side_effect=fake_chat),
        ):
            result = agent.run("今日は池袋に行きます", history=history)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["route"], "chat")
        self.assertIsNone(calls[0]["tools"])
        messages = calls[0]["messages"]
        self.assertEqual(messages[0], {"role": "system", "content": agent.CHAT_SYSTEM_PROMPT})
        self.assertNotIn("書き込み", messages[0]["content"])
        self.assertLessEqual(len(messages[1:-1]), agent._HISTORY_MAX_MESSAGES)
        self.assertEqual(result["reply"], "楽しんできてね。")

    def test_agent_route_keeps_tool_safety_prompt(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_chat(messages, tools=None, temperature=None, model=None, max_tokens=None, route="chat"):
            calls.append({"messages": messages, "tools": tools, "model": model, "route": route})
            return {"role": "assistant", "content": "改善点を整理しました。"}

        with (
            patch.object(agent.project_router, "try_handle_project_turn", return_value=None),
            patch.object(config, "AGENT_MODEL", "agent-test"),
            patch.object(agent, "chat_completion", side_effect=fake_chat),
        ):
            agent.run("この設計を分析して改善して")

        self.assertEqual(calls[0]["route"], "agent")
        self.assertEqual(calls[0]["messages"][0]["content"], agent.AGENT_SYSTEM_PROMPT)
        self.assertIn("実行結果なしに完了したと言わない", agent.AGENT_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
