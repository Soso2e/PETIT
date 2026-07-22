from __future__ import annotations

import ast
import unittest
from pathlib import Path

from backend import agent, model_router


ROOT = Path(__file__).resolve().parents[1]


class VoiceTaskInteractionTests(unittest.TestCase):
    def test_recurring_prompts_are_compact_and_plain_text(self) -> None:
        self.assertLess(len(agent.CHAT_SYSTEM_PROMPT), 120)
        self.assertLess(len(agent.AGENT_SYSTEM_PROMPT), 220)
        self.assertIn("Markdownは使わ", agent.CHAT_SYSTEM_PROMPT)
        self.assertIn("Markdownは使わ", agent.AGENT_SYSTEM_PROMPT)
        self.assertIs(agent.SYSTEM_PROMPT, agent.AGENT_SYSTEM_PROMPT)

    def test_natural_task_edits_route_to_update_tool_only(self) -> None:
        names = agent._related_tool_names("タスクの期限を変更して")
        self.assertIn("update_task", names)
        self.assertNotIn("get_tasks", names)

        names = agent._related_tool_names("あの提出物の締切を来週まで延ばして")
        self.assertIn("update_task", names)

        names = agent._related_tool_names("タスク同期状態を教えて")
        self.assertIn("get_task_sync_status", names)
        self.assertNotIn("get_tasks", names)

    def test_router_can_suggest_all_task_management_tools(self) -> None:
        names = model_router.suggestible_tool_names()
        self.assertIn("update_task", names)
        self.assertIn("get_task_sync_status", names)
        self.assertIn("retry_task_sync", names)
        self.assertLess(len(model_router._ROUTER_SYSTEM_PROMPT), 1000)

    def test_voice_script_is_valid_and_scopes_speech_to_reply_text(self) -> None:
        path = ROOT / "frontend" / "voice.js"
        source = path.read_text(encoding="utf-8")
        self.assertIn("function directReplyText", source)
        self.assertIn("node.nodeType === Node.TEXT_NODE", source)
        self.assertNotIn('const replyText = bubble.textContent || "";', source)
        self.assertIn("function handlePendingVoiceDecision", source)
        self.assertIn("pending.approve.click()", source)
        self.assertIn("pending.cancel.click()", source)
        self.assertIn("function naturalizeCompletedAction", source)

    def test_python_files_parse(self) -> None:
        for relative in ("backend/agent.py", "backend/model_router.py"):
            ast.parse((ROOT / relative).read_text(encoding="utf-8"), filename=relative)


if __name__ == "__main__":
    unittest.main()
