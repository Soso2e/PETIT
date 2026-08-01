from __future__ import annotations

import unittest
from unittest import mock

from backend import agent, capability_router


class CapabilitySelectorTests(unittest.TestCase):
    def test_router_reply_payload_is_not_used_as_final_answer(self) -> None:
        with mock.patch.object(
            capability_router,
            "chat_completion",
            return_value={
                "content": '{"type":"reply","reply":"router response","confidence":0.9}'
            },
        ):
            result = capability_router.choose("こんにちは")

        self.assertEqual(result["type"], "agent")
        self.assertEqual(result["capabilities"], [])
        self.assertEqual(result["goal"], "こんにちは")
        self.assertNotIn("reply", result)

    def test_router_selects_only_registered_capability_groups(self) -> None:
        with mock.patch.object(
            capability_router,
            "chat_completion",
            return_value={
                "content": (
                    '{"capabilities":["lists_and_tasks","unknown","calendar"],'
                    '"goal":"今日のタスクと予定を確認する","confidence":0.8}'
                )
            },
        ):
            result = capability_router.choose("今日なにする？")

        self.assertEqual(result["type"], "agent")
        self.assertEqual(result["capabilities"], ["lists_and_tasks", "calendar"])
        self.assertEqual(result["goal"], "今日のタスクと予定を確認する")

    def test_projects_capability_exposes_registered_status_tool(self) -> None:
        names = capability_router.tool_names_for(["projects"])

        self.assertIn("get_project_status", names)
        self.assertIn("get_tasks", names)


class AgentEntrypointTests(unittest.TestCase):
    def test_greeting_reaches_agent_runtime_instead_of_legacy_instant_reply(self) -> None:
        expected = {"reply": "agent response", "used_tools": []}
        with (
            mock.patch.object(agent.project_router, "try_handle_project_turn", return_value=None),
            mock.patch.object(agent._legacy, "_instant_reply", return_value={"reply": "legacy response"}),
            mock.patch.object(agent._legacy, "_related_tool_names", return_value=[]),
            mock.patch.object(agent.agent_runtime, "run", return_value=expected) as runtime_run,
        ):
            result = agent.run("こんにちは", history=[])

        self.assertEqual(result, expected)
        runtime_run.assert_called_once_with("こんにちは", history=[])


if __name__ == "__main__":
    unittest.main()
