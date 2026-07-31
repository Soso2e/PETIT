from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "backend" / "main.py"


class TtsApiContractTests(unittest.TestCase):
    def test_tts_503_exposes_machine_readable_error_metadata(self) -> None:
        tree = ast.parse(MAIN.read_text(encoding="utf-8"))
        target = next(
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "synthesize_speech"
        )

        response_calls = [
            node
            for node in ast.walk(target)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "JSONResponse"
        ]
        self.assertEqual(len(response_calls), 1)

        call = response_calls[0]
        status_keyword = next(
            keyword for keyword in call.keywords if keyword.arg == "status_code"
        )
        self.assertIsInstance(status_keyword.value, ast.Constant)
        self.assertEqual(status_keyword.value.value, 503)

        source = MAIN.read_text(encoding="utf-8")
        for field in (
            '"error"',
            '"error_code"',
            '"retryable"',
            '"upstream_status"',
            '"retry_after_seconds"',
        ):
            self.assertIn(field, source)

        self.assertIn("exc.code", source)
        self.assertIn("exc.retryable", source)
        self.assertIn("exc.status_code", source)
        self.assertIn("exc.retry_after_seconds", source)


if __name__ == "__main__":
    unittest.main()
