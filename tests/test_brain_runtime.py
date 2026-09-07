from __future__ import annotations

import unittest
from unittest.mock import patch

from backend import brain_runtime


class BrainRuntimeTests(unittest.TestCase):
    def test_direct_reply_is_observed_as_one_llm_call(self) -> None:
        route = {
            "type": "reply",
            "reply": "それなら今日は早めに休んだ方がよさそう。",
            "source": "one_pass_reply",
            "confidence": None,
        }
        with patch.object(brain_runtime.capability_router, "choose", return_value=route):
            result = brain_runtime.run("眠いわ", history=[])

        self.assertEqual(result["model_route"]["llm_call_count"], 1)
        self.assertEqual(result["model_route"]["kind"], "brain")
        self.assertEqual(result["used_tools"], [])

    def test_context_route_uses_second_brain_call(self) -> None:
        route = {
            "type": "context",
            "context_request": {
                "needs": [
                    {"source": "tasks", "priority": "High"},
                    {"source": "calendar", "scope": "tomorrow"},
                ],
                "goal": "明日の負荷を判断",
            },
            "source": "one_pass_context_request",
            "confidence": None,
        }
        packet = {
            "goal": "明日の負荷を判断",
            "sources": [
                {"source": "tasks", "facts": [{"title": "卒研"}], "count": 1},
                {"source": "calendar", "facts": [{"title": "大学"}], "count": 1},
            ],
            "partial": False,
            "errors": [],
        }
        with patch.object(brain_runtime.capability_router, "choose", return_value=route):
            with patch.object(brain_runtime.context_broker, "collect", return_value=packet):
                with patch.object(
                    brain_runtime,
                    "chat_completion",
                    return_value={"content": "明日は大学と卒研があるから、今日少し進めた方がいいよ。"},
                ) as completion:
                    result = brain_runtime.run("明日大丈夫そう？", history=[])

        self.assertEqual(completion.call_count, 1)  # router call is represented by the mocked route
        self.assertEqual(result["model_route"]["llm_call_count"], 2)
        self.assertEqual(result["model_route"]["context_sources"], ["tasks", "calendar"])
        self.assertIn("今日少し", result["reply"])

    def test_deep_agent_route_reuses_existing_runtime_loop(self) -> None:
        route = {
            "type": "agent",
            "capabilities": ["lists_and_tasks"],
            "goal": "タスクを追加する",
            "source": "one_pass_tool_route",
            "confidence": 0.9,
        }
        expected = {"reply": "確認します。", "pending_actions": [{"name": "execute_agent_write"}]}
        with patch.object(brain_runtime.capability_router, "choose", return_value=route):
            with patch.object(brain_runtime.capability_router, "tool_names_for", return_value=["create_task"]):
                with patch.object(brain_runtime.agent_runtime, "_execute_loop", return_value=expected) as execute:
                    result = brain_runtime.run("卒研タスク追加して", history=[])

        self.assertEqual(result["reply"], expected["reply"])
        self.assertEqual(result["pending_actions"], expected["pending_actions"])
        execute.assert_called_once()

    def test_state_reduces_history_and_is_visible_to_router(self) -> None:
        route = {
            "type": "reply",
            "reply": "Context Brokerの続きから進めよう。",
            "source": "one_pass_reply",
            "confidence": None,
        }
        history = []
        for index in range(10):
            history.append({"role": "user", "content": f"user-{index}-" + ("x" * 700)})
            history.append({"role": "assistant", "content": f"assistant-{index}-" + ("y" * 700)})

        with patch.object(brain_runtime.request_context, "current_ids", return_value=("req", "session-a")):
            with patch.object(brain_runtime.conversation_state, "load", return_value={"current_topic": "Context Broker"}):
                with patch.object(
                    brain_runtime.conversation_state,
                    "render_for_model",
                    return_value="[Conversation State]\ncurrent_topic: Context Broker",
                ):
                    with patch.object(brain_runtime.capability_router, "choose", return_value=route) as choose:
                        result = brain_runtime.run("その続きやろう", history=history)

        routed_history = choose.call_args.args[1]
        self.assertIn("Conversation State", routed_history[0]["content"])
        self.assertLessEqual(result["model_route"]["history_messages"], 4)
        self.assertLessEqual(result["model_route"]["history_chars"], 1800)
        self.assertGreater(result["model_route"]["conversation_state_chars"], 0)


if __name__ == "__main__":
    unittest.main()
