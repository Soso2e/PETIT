from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_FLOWS = ROOT / "docs" / "runtime-flows.md"
AGENTS = ROOT / "AGENTS.md"


class RuntimeFlowDocumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime_text = RUNTIME_FLOWS.read_text(encoding="utf-8")
        cls.agents_text = AGENTS.read_text(encoding="utf-8")

    def test_runtime_flow_document_exists_and_contains_mermaid(self) -> None:
        self.assertTrue(RUNTIME_FLOWS.is_file())
        self.assertGreaterEqual(self.runtime_text.count("```mermaid"), 8)

    def test_runtime_flow_covers_required_execution_paths(self) -> None:
        required_sections = (
            "## 1. 会話全体フロー",
            "## 2. Capability Selector",
            "## 3. Agent Tool Loop",
            "## 4. Tool Registryとリスク判定",
            "## 5. 確認付き書き込みと再開",
            "## 6. 進捗表示",
            "## 8. Project Continuityの決定論的フロー",
            "## 9. チャットで行えることの全体像",
        )
        for section in required_sections:
            with self.subTest(section=section):
                self.assertIn(section, self.runtime_text)

    def test_tool_loop_stop_conditions_are_documented(self) -> None:
        for marker in (
            "tool_iteration_limit",
            "tool_call_limit",
            "duplicate_tool_call",
            "tool_not_allowed",
            "invalid_tool_arguments",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.runtime_text)

    def test_confirmation_state_and_resume_are_documented(self) -> None:
        for marker in (
            "execute_agent_write",
            "Agent state",
            "resume_after_write",
            "approval_id",
            "request_id",
            "session_id",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.runtime_text)

    def test_capabilities_and_progress_jobs_are_documented(self) -> None:
        for marker in (
            "lists_and_tasks",
            "calendar",
            "knowledge",
            "github",
            "web",
            "memory",
            "projects",
            "planning / tool_started / tool_finished / finalizing",
            "SQLite jobs",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.runtime_text)

    def test_agents_requires_runtime_diagram_sync(self) -> None:
        self.assertIn("docs/runtime-flows.md", self.agents_text)
        self.assertIn("同じ変更内で対応するMermaid図も必ず更新", self.agents_text)
        self.assertIn("実装とMermaid図が一致しない状態でコミット・main反映しない", self.agents_text)


if __name__ == "__main__":
    unittest.main()
