"""Local development evidence acceptance and safety tests (#341)."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from backend import config, workspace_context as context
from backend.tools.local_development import get_local_development_status


class LocalDevelopmentTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        for key, value in {
            "WORKSPACE_CONTEXT_ENABLED": True,
            "WORKSPACE_LOCAL_DEVELOPMENT_ENABLED": True,
            "WORKSPACE_CONTEXT_DIRS": [self.root],
            "WORKSPACE_CONTEXT_FOREGROUND_ENABLED": False,
        }.items():
            patcher = patch.object(config, key, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.observer = context.WorkspaceObserver()
        patcher = patch.object(context, "_observer", self.observer)
        patcher.start()
        self.addCleanup(patcher.stop)

    def git(self, *args: str) -> str:
        return subprocess.run(["git", "-C", str(self.root), *args], check=True,
                              capture_output=True, text=True).stdout

    def initialize(self) -> None:
        self.git("init", "-b", "main")
        (self.root / "Concept.md").write_text("# 目的\n魔法を編む", encoding="utf-8")
        (self.root / "PROGRESS.md").write_text(
            "# 進捗\nimplemented: yes\nAPI_KEY=never-publish-this", encoding="utf-8")
        (self.root / "README.md").write_text("# setup", encoding="utf-8")
        (self.root / ".env").write_text("TOKEN=do-not-read", encoding="utf-8")
        self.git("add", "Concept.md", "PROGRESS.md", "README.md")
        self.git("-c", "user.name=Tester", "-c", "user.email=bot@example.invalid",
                 "commit", "-m", "initial")
        self.git("switch", "-c", "feat/magic")
        (self.root / "code.py").write_text("print('spell')", encoding="utf-8")
        self.git("add", "code.py")
        self.git("-c", "user.name=Tester", "-c", "user.email=bot@example.invalid",
                 "commit", "-m", "magical combat loop")

    def test_git_evidence_and_allowlisted_documents(self):
        self.initialize()
        index_before = (self.root / ".git/index").read_bytes()
        result = context.observe_workspace(self.root)
        self.assertEqual(result["branch"], "feat/magic")
        self.assertEqual(result["status"], "ok")
        evidence = result["development"]
        self.assertEqual(evidence["source"], "local_checkout")
        self.assertEqual(evidence["remote_ref_freshness"], "unknown_no_fetch")
        self.assertTrue(evidence["head_sha"])
        self.assertTrue(any(item["name"] == "feat/magic" for item in evidence["branches"]))
        self.assertEqual(evidence["main_comparison"]["ahead"], 1)
        self.assertEqual(evidence["main_comparison"]["behind"], 0)
        self.assertIn("magical combat loop", evidence["recent_commits"][0]["subject"])
        docs = {item["name"]: item for item in evidence["documents"]}
        self.assertIn("魔法を編む", docs["Concept.md"]["excerpt"])
        self.assertIn("implemented: yes", docs["PROGRESS.md"]["excerpt"])
        self.assertNotIn("never-publish-this", docs["PROGRESS.md"]["excerpt"])
        self.assertEqual(sorted(docs), ["Concept.md", "PROGRESS.md", "README.md"])
        self.assertNotIn("do-not-read", json.dumps(result))
        self.assertNotIn(str(self.root), json.dumps(result))
        self.assertEqual(index_before, (self.root / ".git/index").read_bytes())

    def test_missing_documents_are_not_fabricated(self):
        self.initialize()
        (self.root / "README.md").unlink()
        result = context.observe_workspace(self.root)
        docs = {doc["name"]: doc for doc in result["development"]["documents"]}
        self.assertEqual(docs["README.md"]["status"], "missing")

    def test_document_symlink_is_excluded(self):
        self.initialize()
        target = self.root / "private.txt"
        target.write_text("private content")
        doc = self.root / "Concept.md"
        doc.unlink()
        try:
            doc.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("Symlink creation unavailable")
        result = context.observe_workspace(self.root)
        self.assertEqual(result["development"]["documents"][0]["status"], "excluded_symlink")
        self.assertNotIn("private content", json.dumps(result))

    def test_disabled_detail_preserves_existing_git_observation(self):
        self.initialize()
        with patch.object(config, "WORKSPACE_LOCAL_DEVELOPMENT_ENABLED", False):
            result = context.observe_workspace(self.root)
        self.assertEqual(result["status"], "ok")
        self.assertNotIn("development", result)

    def test_read_only_cached_tool_and_missing_selection(self):
        self.initialize()
        self.observer.refresh()
        with patch.object(context, "_command") as command:
            result = get_local_development_status(self.root.name)
            unknown = get_local_development_status("unregistered")
        command.assert_not_called()
        self.assertTrue(result["ok"])
        self.assertEqual(result["workspace"]["branch"], "feat/magic")
        self.assertEqual(unknown["status"], "not_found_or_ambiguous")
        summary = get_local_development_status()
        self.assertEqual(summary["workspace"]["branch"], "feat/magic")

    def test_stale_snapshot_is_never_treated_as_current(self):
        self.initialize()
        self.observer.refresh()
        self.observer._snapshot["collected_at"] = (
            datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        result = get_local_development_status()
        self.assertEqual(result["status"], "stale_or_pending")
        self.assertNotIn("workspace", result)

    def test_model_summary_labels_untrusted_document_evidence(self):
        self.initialize()
        self.observer.refresh()
        block = context.build_context_block()
        self.assertIn("Concept.md", block)
        self.assertIn("PROGRESS.md", block)
        self.assertIn("未信頼", block)
        self.assertIn("fetchしていない", block)


if __name__ == "__main__":
    unittest.main()
