from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from backend import config, db, project_continuity as projects, project_workspaces as folders, tools, workspace_context
from backend.tools.local_development import get_local_development_status
from backend.tools.project_workspaces import find_projects, register_project


class ProjectWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.first = self.base / "one" / "Python_Tools"
        self.second = self.base / "two" / "Python_Tools"
        for root in (self.first, self.second):
            root.mkdir(parents=True)
            (root / "PROGRESS.md").write_text("# 現在地\n実装済み。実機は未確認。", encoding="utf-8")
            self.git(root, "init", "-b", "main")
            self.git(root, "add", "PROGRESS.md")
            self.git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "fixture")
        for key, value in {
            "DB_PATH": self.base / "app.db", "WORKSPACE_CONTEXT_ENABLED": True,
            "WORKSPACE_LOCAL_DEVELOPMENT_ENABLED": True, "WORKSPACE_CONTEXT_FOREGROUND_ENABLED": False,
            "WORKSPACE_CONTEXT_DIRS": [self.first, self.second],
            "notion_configured": lambda: False,
        }.items():
            p = patch.object(config, key, value); p.start(); self.addCleanup(p.stop)
        db.init_db()
        self.observer = workspace_context.WorkspaceObserver()
        p = patch.object(workspace_context, "_observer", self.observer); p.start(); self.addCleanup(p.stop)
        self.project = projects.create_project("卒研")
        self.other = projects.create_project("Python_Tools")
        self.observer.refresh()
        tools.register_builtin_tools()

    def git(self, root, *args):
        return subprocess.run(["git", "-C", str(root), *args], check=True,
                              capture_output=True, text=True).stdout

    def test_similar_names_and_same_basename_never_create_mapping(self):
        result = get_local_development_status(project_id=self.other["id"])
        self.assertEqual(result["status"], "project_workspace_not_linked")
        self.assertEqual(folders.links(self.other["id"]), [])

    def test_confirmed_mapping_selects_exact_repository_and_preserves_evidence_types(self):
        saved = folders.link(self.project["id"], str(self.second))
        self.assertTrue(saved["source_link"]["confirmed_at"])
        (self.second / "PROGRESS.md").write_text("# 現在地\n変更したがテスト未実施。", encoding="utf-8")
        self.observer.refresh()
        result = get_local_development_status(project_id=self.project["id"])
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["workspaces"]), 1)
        observed = result["workspaces"][0]["workspace"]
        self.assertGreater(observed["changed_entries"], 0)
        development = observed["development"]
        self.assertEqual(development["head_sha"], self.git(self.second, "rev-parse", "HEAD").strip())
        progress = next(doc for doc in development["documents"] if doc["name"] == "PROGRESS.md")
        self.assertTrue(progress["modified_at"])
        self.assertEqual(progress["source"]["relative_path"], "PROGRESS.md")
        self.assertEqual(progress["verification"], "document_claims_not_execution_evidence")
        self.assertTrue(result["collected_at"])

    def test_unconfirmed_link_is_never_read(self):
        projects.link_project_source(self.project["id"], folders.PROVIDER, str(self.first),
                                     metadata={"path": str(self.first)}, confirmed=False)
        self.assertEqual(get_local_development_status(project_id=self.project["id"])["status"],
                         "project_workspace_not_linked")

    def test_link_and_unlink_are_confirmation_tools_and_do_not_delete_files(self):
        self.assertTrue(tools.requires_confirmation("link_project_workspace"))
        self.assertTrue(tools.requires_confirmation("unlink_project_workspace"))
        self.assertTrue(tools.requires_confirmation("register_project"))
        saved = folders.link(self.project["id"], str(self.first))["source_link"]
        with self.assertRaises(ValueError):
            folders.link(self.other["id"], str(self.first))
        removed = folders.unlink(self.project["id"], saved["id"])["source_link"]
        self.assertEqual(removed["status"], "removed")
        self.assertTrue((self.first / "PROGRESS.md").exists())
        changed = folders.link(self.other["id"], str(self.first))["source_link"]
        self.assertEqual(changed["project_id"], self.other["id"])

    def test_task_project_id_is_the_same_project_used_by_folder_observation(self):
        folders.link(self.project["id"], str(self.first))
        task = json.loads(tools.dispatch("create_task", {"title": "卒研発表の準備", "project_id": self.project["id"]}))["task"]
        result = json.loads(tools.dispatch("get_tasks", {"project_id": task["project_id"]}))
        self.assertIn(task["id"], [item["id"] for item in result["tasks"]])
        self.assertTrue(get_local_development_status(project_id=task["project_id"])["ok"])

    def test_removed_allowlist_missing_root_and_disabled_flags_fail_closed(self):
        folders.link(self.project["id"], str(self.first))
        with patch.object(config, "WORKSPACE_CONTEXT_DIRS", [self.second]):
            self.assertFalse(get_local_development_status(project_id=self.project["id"])["ok"])
        with patch.object(config, "WORKSPACE_CONTEXT_ENABLED", False):
            self.assertEqual(get_local_development_status(project_id=self.project["id"])["status"], "disabled")

    def test_stale_cache_does_not_become_current_just_because_a_file_was_modified(self):
        folders.link(self.project["id"], str(self.first))
        self.observer._snapshot["collected_at"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        result = get_local_development_status(project_id=self.project["id"])
        self.assertTrue(result["stale"])
        self.assertFalse(result["ok"])

    def test_private_subfolders_and_unregistered_roots_are_rejected(self):
        private = self.base / "_private"
        private.mkdir()
        with patch.object(config, "WORKSPACE_CONTEXT_DIRS", [private]):
            with self.assertRaises(ValueError):
                folders.link(self.project["id"], str(private))
        with self.assertRaises(ValueError):
            folders.link(self.project["id"], str(self.base))

    def test_symlink_target_is_revalidated_at_execution(self):
        alias = self.base / "alias"
        try:
            alias.symlink_to(self.first, target_is_directory=True)
        except OSError:
            self.skipTest("symlink creation unavailable")
        with patch.object(config, "WORKSPACE_CONTEXT_DIRS", [alias]):
            with self.assertRaises(ValueError):
                folders.link(self.project["id"], str(alias))

    def test_explicit_project_lookup_returns_ambiguity_and_registration_reuses_known_project(self):
        self.assertEqual(find_projects("卒研")["status"], "unique")
        reused = register_project("卒研")
        self.assertTrue(reused["already_exists"])
        self.assertEqual(reused["project"]["id"], self.project["id"])
        projects.add_project_alias(self.other["id"], "卒研")
        self.assertEqual(find_projects("卒研")["status"], "ambiguous")
        with self.assertRaises(ValueError):
            register_project("卒研")


if __name__ == "__main__":
    unittest.main()
