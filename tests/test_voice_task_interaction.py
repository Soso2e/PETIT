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
    def test_recurring_prompts_are_compact_and_plain_text(self) -> None:
        _source, module = _module("backend/agent.py")
        chat_prompt = _literal_assignment(module, "CHAT_SYSTEM_PROMPT")
        agent_prompt = _literal_assignment(module, "AGENT_SYSTEM_PROMPT")
        self.assertLess(len(chat_prompt), 120)
        self.assertLess(len(agent_prompt), 220)
        self.assertIn("Markdownは使わ", chat_prompt)
        self.assertIn("Markdownは使わ", agent_prompt)

    def test_task_edit_signals_and_read_tool_exclusion_are_present(self) -> None:
        source, _module_ast = _module("backend/agent.py")
        for marker in (
            '"update_task"', '"締切を延ば"', '"日付を変"',
            '"get_task_sync_status"', '"retry_task_sync"',
        ):
            self.assertIn(marker, source)
        self.assertIn('names = [name for name in names if name != "get_tasks"]', source)

    def test_router_can_suggest_all_task_management_tools(self) -> None:
        source, module = _module("backend/model_router.py")
        names = _literal_assignment(module, "_SUGGESTIBLE_TOOLS")
        self.assertIn("update_task", names)
        self.assertIn("get_task_sync_status", names)
        self.assertIn("retry_task_sync", names)
        self.assertIn("PETITの経路選択器", source)
        self.assertIn("JSONだけ返し", source)

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
        for relative in ("backend/agent.py", "backend/model_router.py"):
            _module(relative)


if __name__ == "__main__":
    unittest.main()
