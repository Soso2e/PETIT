from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

from backend import agent, agent_runtime, config, lmstudio_client


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

    def test_simple_chat_uses_bounded_context_and_router_reply(self) -> None:
        captured: list[dict[str, object]] = []

        def fake_choose(message, history=None):
            captured.append({"message": message, "history": history})
            return {
                "type": "reply",
                "reply": "楽しんできてね。",
                "source": "llm",
                "confidence": 0.95,
            }

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
            patch.object(agent.model_router, "choose", side_effect=fake_choose),
            patch.object(agent, "chat_completion") as completion,
        ):
            result = agent.run("今日は池袋に行きます", history=history)

        completion.assert_not_called()
        self.assertEqual(len(captured), 1)
        routed_history = captured[0]["history"]
        self.assertLessEqual(len(routed_history), agent._HISTORY_MAX_MESSAGES)
        self.assertLessEqual(sum(len(item["content"]) for item in routed_history), agent._HISTORY_MAX_CHARS)
        self.assertEqual(result["reply"], "楽しんできてね。")
        self.assertEqual(result["model_route"]["actual_route"], "chat")

    def test_agent_route_keeps_tool_safety_prompt(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_chat(messages, tools=None, temperature=None, model=None, max_tokens=None, route="chat"):
            calls.append({"messages": messages, "tools": tools, "model": model, "route": route})
            return {"role": "assistant", "content": "改善点を整理しました。", "tool_calls": []}

        route = {
            "type": "agent",
            "capabilities": [],
            "goal": "設計を分析する",
            "source": "llm",
            "confidence": 0.9,
        }
        with (
            patch.object(agent.project_router, "try_handle_project_turn", return_value=None),
            patch.object(agent.model_router, "choose", return_value=route),
            patch.object(config, "AGENT_MODEL", "agent-test"),
            patch.object(agent, "chat_completion", side_effect=fake_chat),
        ):
            agent.run("この設計を分析して改善して")

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["route"], "agent")
        self.assertIn("直接対応Toolをcallする", agent_runtime._AGENT_SYSTEM_PROMPT)
        self.assertIn("事実に基づき", agent_runtime._AGENT_SYSTEM_PROMPT)



class EmptyModelResponseRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.endpoint_patch = patch.object(
            lmstudio_client,
            "endpoint",
            side_effect=lambda route: {
                "configured": True,
                "provider": "lm_studio",
                "label": "LM Studio",
                "base_url": "http://localhost:1234/v1",
                "api_key": "lm-studio",
                "model": "local-model",
                "profile": "local",
            },
        )
        self.endpoint_patch.start()

    def tearDown(self) -> None:
        self.endpoint_patch.stop()

    @staticmethod
    def _response(content: str, *, finish_reason: str = "stop") -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": finish_reason,
                    }
                ]
            },
            request=httpx.Request("POST", "http://localhost:1234/v1/chat/completions"),
        )

    def test_empty_content_retries_with_compact_context(self) -> None:
        responses = [self._response(""), self._response("復旧しました。")]
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "前の質問"},
            {"role": "assistant", "content": "前の回答"},
            {"role": "user", "content": "Linkraftって知ってる？"},
        ]

        with patch.object(lmstudio_client.httpx, "post", side_effect=responses) as post:
            result = lmstudio_client.chat_completion(messages, route="chat")

        self.assertEqual(result["content"], "復旧しました。")
        self.assertTrue(result["_empty_response_recovered"])
        self.assertEqual(post.call_count, 2)
        retry_payload = post.call_args_list[1].kwargs["json"]
        self.assertEqual(
            retry_payload["messages"],
            [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "Linkraftって知ってる？"},
            ],
        )
        self.assertEqual(retry_payload["temperature"], 0)
        self.assertEqual(retry_payload["chat_template_kwargs"], {"enable_thinking": False})

    def test_two_empty_responses_return_stable_fallback(self) -> None:
        responses = [self._response(""), self._response("")]
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "Linkraft"},
        ]

        with patch.object(lmstudio_client.httpx, "post", side_effect=responses) as post:
            result = lmstudio_client.chat_completion(messages, route="chat")

        self.assertEqual(result["content"], lmstudio_client._EMPTY_REPLY_FALLBACK)
        self.assertEqual(result["_finish_reason"], "empty_response_fallback")
        self.assertEqual(post.call_count, 2)

    def test_tool_call_is_usable_even_when_content_is_empty(self) -> None:
        response = httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {"name": "get_tasks", "arguments": "{}"},
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
            request=httpx.Request("POST", "http://localhost:1234/v1/chat/completions"),
        )

        with patch.object(lmstudio_client.httpx, "post", return_value=response) as post:
            result = lmstudio_client.chat_completion(
                [{"role": "user", "content": "タスクを見せて"}],
                tools=[{"type": "function", "function": {"name": "get_tasks"}}],
                route="agent",
            )

        self.assertEqual(len(result["tool_calls"]), 1)
        self.assertEqual(post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
