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
            "## v0.34.0: 初期設定・優先順位と単一Brain",
            "## Claude Code CLI Executor",
            "## Antigravity CLI Brainと開発タスク",
            "## #368: Workspace・永続Provider補助Thread・動的Tool公開",
            "## #372: Durable Read Task P0",
            "## 画像付き会話のRead専用経路",
            "## 保守ルール",
        )
        for section in required_sections:
            with self.subTest(section=section):
                self.assertIn(section, self.runtime_text)

    def test_single_brain_stop_conditions_and_approval_are_documented(self) -> None:
        for marker in (
            "8 rounds / 12 calls",
            "cli_only",
            "discover_tools",
            "一度だけ承認消費",
            "receipt",
            "Tool後の障害",
            "vision_reply.run_with_images",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.runtime_text)

    def test_retired_routing_is_archived_not_current(self) -> None:
        archive = ROOT / "docs" / "archive" / "runtime-flows-legacy-routing.md"
        self.assertTrue(archive.is_file())
        self.assertIn("アーカイブ", archive.read_text(encoding="utf-8"))
        for retired in ("## 2. PETIT Brain / Context Broker", "resume_after_write", "capability_router"):
            with self.subTest(retired=retired):
                self.assertNotIn(retired, self.runtime_text)

    def test_agents_requires_runtime_diagram_sync(self) -> None:
        self.assertIn("docs/runtime-flows.md", self.agents_text)
        self.assertIn("同じ変更内で対応するMermaid図も必ず更新", self.agents_text)
        self.assertIn("実装とMermaid図が一致しない状態でコミット・main反映しない", self.agents_text)


if __name__ == "__main__":
    unittest.main()
