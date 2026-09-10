from __future__ import annotations

import ast
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _module(relative: str) -> tuple[str, ast.Module]:
    source = (ROOT / relative).read_text(encoding="utf-8")
    return source, ast.parse(source, filename=relative)


def _literal_assignment(module: ast.Module, name: str) -> Any:
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"assignment not found: {name}")


class VoiceTaskInteractionTests(unittest.TestCase):
    def test_shared_prompt_preserves_speech_friendly_output(self) -> None:
        # Issue #235 unified both aliases; they are no longer string literals.
        _source, module = _module("backend/petit_prompt.py")
        prompt = _literal_assignment(module, "CORE_SYSTEM_PROMPT")
        self.assertIn("PETIT", prompt)
        self.assertIn("読み上げやすいプレーンテキスト", prompt)
        _source, agent_module = _module("backend/agent.py")
        for name in ("CHAT_SYSTEM_PROMPT", "AGENT_SYSTEM_PROMPT"):
            assignment = next(node for node in agent_module.body if isinstance(node, ast.Assign)
                              and any(isinstance(target, ast.Name) and target.id == name for target in node.targets))
            self.assertIsInstance(assignment.value, ast.Name)
            self.assertEqual(assignment.value.id, "CORE_SYSTEM_PROMPT")

    def test_task_management_is_exposed_as_one_contextual_capability(self) -> None:
        source, _module_ast = _module("backend/capability_router.py")
        for marker in (
            '"lists_and_tasks"',
            '"get_lists"',
            '"add_list_item"',
            '"get_tasks"',
            '"create_task"',
            '"update_task"',
            '"get_task_sync_status"',
            '"retry_task_sync"',
        ):
            self.assertIn(marker, source)
        self.assertIn("route_to_agent", source)
        self.assertIn('"fallback_read"', source)
        self.assertNotIn("_TASK_TOOL_SIGNALS", (ROOT / "backend" / "agent.py").read_text(encoding="utf-8"))

    def test_agent_runtime_keeps_confirmation_and_bounded_loop(self) -> None:
        source = (ROOT / "backend" / "agent_runtime.py").read_text(encoding="utf-8")
        self.assertIn("config.MAX_TOOL_ITERATIONS", source)
        self.assertIn("_MAX_TOOL_CALLS = 6", source)
        self.assertIn("tools.requires_confirmation", source)
        self.assertIn('"execute_agent_write"', source)
        self.assertIn("duplicate_tool_call", source)

    def test_voice_script_scopes_speech_and_handles_confirmation(self) -> None:
        source = (ROOT / "frontend" / "voice.js").read_text(encoding="utf-8")
        self.assertIn("function directReplyText", source)
        self.assertIn("node.nodeType === Node.TEXT_NODE", source)
        self.assertNotIn('const replyText = bubble.textContent || "";', source)
        self.assertIn("function handlePendingVoiceDecision", source)
        self.assertIn("pending.approve.click()", source)
        self.assertIn("pending.cancel.click()", source)
        self.assertIn("function naturalizeCompletedAction", source)

    def test_python_files_parse(self) -> None:
        for relative in (
            "backend/agent.py",
            "backend/agent_runtime.py",
            "backend/capability_router.py",
        ):
            _module(relative)


if __name__ == "__main__":
    unittest.main()
