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
        # The single Brain uses the same shared prompt (legacy aliases were removed with the router).
        self.assertIn("CORE_SYSTEM_PROMPT", (ROOT / "backend" / "brain.py").read_text(encoding="utf-8"))

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
            "backend/brain.py",
            "backend/vision_reply.py",
        ):
            _module(relative)


if __name__ == "__main__":
    unittest.main()
