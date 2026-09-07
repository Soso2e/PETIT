from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import capability_router, config, workspace_context as context
from backend.app import create_app


class WorkspaceContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.observer = context.WorkspaceObserver()
        for key, value in {
            "WORKSPACE_CONTEXT_ENABLED": True,
            "WORKSPACE_CONTEXT_DIRS": [self.root],
            "WORKSPACE_CONTEXT_FOREGROUND_ENABLED": False,
            "WORKSPACE_CONTEXT_MAX_AGE_SECONDS": 90,
        }.items():
            patcher = patch.object(config, key, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(context, "_observer", self.observer)
        patcher.start()
        self.addCleanup(patcher.stop)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], check=True,
                              capture_output=True, text=True).stdout

    def init_repo(self):
        self.git("init", "-b", "main")
        (self.root / "app.py").write_text("initial\n")
        self.git("add", "app.py")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "initial")

    def test_real_repository_observation_does_not_change_index_or_contents(self):
        self.init_repo()
        (self.root / "app.py").write_text("edited private body\n")
        (self.root / "new.txt").write_text("untracked private body")
        before = (self.root / ".git/index").read_bytes()
        result = context.observe_workspace(self.root)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["changed_entries"], 2)
        self.assertEqual(result["branch"], "main")
        self.assertEqual(before, (self.root / ".git/index").read_bytes())
        self.assertNotIn("private body", json.dumps(result))
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_subdirectory_does_not_observe_parent_repository(self):
        self.init_repo()
        child = self.root / "child"
        child.mkdir()
        result = context.observe_workspace(child)
        self.assertEqual(result["error"], "not_repository_root")
        self.assertNotIn("files", result)

    def test_conflicts_renames_private_paths_and_unicode(self):
        output = ("## main\0UU 競合.py\0R  新規.py\0旧名.py\0"
                  "?? .env.production\0?? secrets/\0 M key.pem\0 M ordinary.py\0").encode()
        with patch.object(context, "_command", side_effect=[str(self.root).encode(), output]):
            result = context.observe_workspace(self.root)
        self.assertEqual(result["conflicts"], 1)
        self.assertEqual(result["changed_entries"], 6)
        self.assertEqual(result["hidden_entries"], 3)
        self.assertEqual([item["path"] for item in result["files"]], ["競合.py", "新規.py", "ordinary.py"])

    def test_file_list_is_bounded(self):
        output = b"## main\0" + b"".join(f" M file-{i}.py\0".encode() for i in range(20))
        with patch.object(context, "_command", side_effect=[str(self.root).encode(), output]):
            result = context.observe_workspace(self.root)
        self.assertEqual(result["changed_entries"], 20)
        self.assertEqual(len(result["files"]), 8)
        self.assertTrue(result["files_truncated"])

    def test_timeout_is_not_a_clean_repository_and_does_not_leak_exception(self):
        with patch.object(context, "_command", side_effect=subprocess.TimeoutExpired("private path", 5)):
            result = context.observe_workspace(self.root)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["error"], "timeout")
        self.assertNotIn("changed_entries", result)
        self.assertNotIn("private", json.dumps(result))

    def test_one_failed_repository_preserves_other_observations(self):
        with (
            patch.object(config, "WORKSPACE_CONTEXT_DIRS", [self.root, self.root / "absent"]),
            patch.object(context, "observe_workspace", side_effect=[
                {"name": "one", "status": "ok", "changed_entries": 2},
                {"name": "two", "status": "unavailable", "error": "observation_failed"},
            ]),
        ):
            self.observer.refresh()
        snapshot = self.observer.snapshot()
        self.assertEqual(snapshot["workspaces"][0]["changed_entries"], 2)
        self.assertEqual(snapshot["workspaces"][1]["status"], "unavailable")

    def test_disabled_does_not_observe_or_inject_or_return_old_data(self):
        with patch.object(config, "WORKSPACE_CONTEXT_ENABLED", False), patch.object(context, "_command") as command:
            self.observer.start()
            self.observer.refresh()
            self.assertEqual(context.build_context_block(), "")
            self.assertEqual(context.get_workspace_context(), {"enabled": False, "status": "disabled"})
        command.assert_not_called()
        self.assertIsNone(self.observer._thread)

    def test_stale_observations_are_not_injected_as_current_facts(self):
        self.observer._snapshot = {
            "collected_at": (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat(),
            "foreground": {"status": "ok", "application": "old-app"},
            "workspaces": [{"name": "old-workspace"}],
        }
        self.assertTrue(self.observer.snapshot()["stale"])
        block = context.build_context_block()
        self.assertIn("不明", block)
        self.assertNotIn("old-app", block)
        self.assertNotIn("old-workspace", block)

    def test_api_and_brain_use_cached_observation_without_commands(self):
        self.init_repo()
        self.observer.refresh()
        with (
            patch.object(context, "_command") as command,
            patch.object(capability_router.situation, "build_active_work_context", return_value=""),
            patch.object(capability_router, "chat_completion", return_value={"content": "変更はないよ。"}) as llm,
        ):
            client = TestClient(create_app())  # do not start live services
            response = client.get("/api/workspace-context")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["workspaces"][0]["changed_entries"], 0)
            result = capability_router.choose("今のGit作業環境は？")
        command.assert_not_called()
        llm.assert_called_once()
        self.assertEqual(result["type"], "reply")
        self.assertIn("【PC作業環境】", llm.call_args.args[0][-1]["content"])

    def test_foreground_opt_in_and_unavailable_platform(self):
        with patch.object(context, "_command") as command:
            self.assertEqual(context.observe_foreground(), {"status": "disabled"})
        command.assert_not_called()
        with patch.object(config, "WORKSPACE_CONTEXT_FOREGROUND_ENABLED", True), patch.object(context.platform, "system", return_value="Linux"):
            self.assertEqual(context.observe_foreground(), {"status": "unsupported"})

    def test_mac_foreground_collects_only_application_identifier(self):
        with (
            patch.object(config, "WORKSPACE_CONTEXT_FOREGROUND_ENABLED", True),
            patch.object(context.platform, "system", return_value="Darwin"),
            patch.object(context, "_command", return_value=b"com.microsoft.VSCode\n") as command,
        ):
            self.assertEqual(context.observe_foreground()["application"], "com.microsoft.VSCode")
        self.assertNotIn("window", command.call_args.args[0][-1].lower())

    def test_stop_discards_observations(self):
        self.init_repo()
        self.observer.refresh()
        self.observer.stop()
        self.observer.refresh()
        self.assertEqual(self.observer.snapshot()["status"], "pending")


if __name__ == "__main__":
    unittest.main()
