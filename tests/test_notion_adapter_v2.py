from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import (
    config,
    db,
    notion_client,
    notion_project_links,
    notion_project_sync,
    project_continuity,
    project_resume,
    tools,
)
from backend.notion_client import NotionError


class NotionAdapterV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(config, "DB_PATH", Path(self.temp_dir.name) / "app.db")
        self.db_patch.start()
        self.config_patch = patch.multiple(
            config,
            NOTION_API_KEY="test-key",
            NOTION_PROJECTS_DB_ID="projects-db",
            NOTION_TASKS_DB_ID="tasks-db",
            NOTION_PROP_TITLE="タスク名",
            NOTION_PROP_STATUS="ステータス",
            NOTION_PROP_DUE="期限",
            NOTION_PROP_PRIORITY="優先度",
            NOTION_PROP_CATEGORY="タグ",
            NOTION_PROP_REASON="理由",
            NOTION_PROP_DONE_DATE="完了日",
            NOTION_PROJECT_PROP_TITLE="プロジェクト名",
            NOTION_PROJECT_PROP_STATUS="ステータス",
            NOTION_PROJECT_PROP_OWNER="オーナー",
            NOTION_PROJECT_PROP_PRIORITY="優先度",
            NOTION_PROJECT_PROP_PERIOD="期間",
            NOTION_PROJECT_PROP_SUMMARY="要約",
            NOTION_PROJECT_PROP_TASKS="タスク",
            NOTION_PROJECT_PROP_BLOCKED_BY="次のプロジェクトを保留中：",
            NOTION_TASK_PROP_PROJECT="プロジェクト",
            NOTION_TASK_PROP_ASSIGNEE="担当者",
            NOTION_TASK_PROP_PARENT="親タスク",
            NOTION_TASK_PROP_SUBTASKS="サブタスク",
            NOTION_TASK_PROP_SUMMARY="要約",
        )
        self.config_patch.start()
        db.init_db()
        project_continuity.ensure_project_schema()
        notion_project_sync.ensure_notion_project_schema()
        notion_project_sync._last_sync_monotonic.clear()

    def tearDown(self) -> None:
        self.config_patch.stop()
        self.db_patch.stop()
        self.temp_dir.cleanup()

    @staticmethod
    def rich_text(value: str) -> dict:
        return {"rich_text": [{"plain_text": value}]}

    @staticmethod
    def title(value: str) -> dict:
        return {"title": [{"plain_text": value}]}

    @staticmethod
    def relation(*ids: str) -> dict:
        return {"relation": [{"id": item} for item in ids]}

    @staticmethod
    def people(*ids: str) -> dict:
        return {"people": [{"id": item} for item in ids]}

    def project_page(self, external_id: str = "notion-project-petit", title: str = "PETIT") -> dict:
        return {
            "id": external_id,
            "url": f"https://notion.so/{external_id}",
            "created_time": "2026-07-01T00:00:00.000Z",
            "last_edited_time": "2026-07-18T01:00:00.000Z",
            "archived": False,
            "properties": {
                "プロジェクト名": self.title(title),
                "ステータス": {"status": {"name": "進行中"}},
                "オーナー": self.people("notion-user-soso"),
                "優先度": {"select": {"name": "高"}},
                "期間": {"date": {"start": "2026-07-01", "end": "2026-07-31"}},
                "要約": self.rich_text("個人AIアシスタント"),
                "タスク": self.relation("task-a", "task-b"),
                "次のプロジェクトを保留中：": self.relation("notion-project-blocker"),
            },
        }

    def task_page(self, external_id: str = "task-a") -> dict:
        return {
            "id": external_id,
            "url": f"https://notion.so/{external_id}",
            "created_time": "2026-07-01T00:00:00.000Z",
            "last_edited_time": "2026-07-18T02:00:00.000Z",
            "archived": False,
            "properties": {
                "タスク名": self.title("Notion Adapter v2を実装"),
                "ステータス": {"status": {"name": "進行中"}},
                "期限": {"date": {"start": "2026-07-20", "end": None}},
                "優先度": {"select": {"name": "高"}},
                "タグ": {"multi_select": [{"name": "改善"}]},
                "理由": self.rich_text("Relationを失わないため"),
                "完了日": {"date": None},
                "要約": self.rich_text("プロジェクトとタスクを同期する"),
                "プロジェクト": self.relation("notion-project-petit"),
                "担当者": self.people("notion-user-soso", "notion-user-helper"),
                "親タスク": self.relation("task-parent"),
                "サブタスク": self.relation("task-child-a", "task-child-b"),
            },
        }

    def test_project_parser_preserves_people_period_and_relations(self) -> None:
        parsed = notion_client.parse_project_page(self.project_page())
        self.assertEqual(parsed["title"], "PETIT")
        self.assertEqual(parsed["owner_external_ids"], ["notion-user-soso"])
        self.assertEqual(parsed["period_start"], "2026-07-01")
        self.assertEqual(parsed["period_end"], "2026-07-31")
        self.assertEqual(parsed["task_external_ids"], ["task-a", "task-b"])
        self.assertEqual(parsed["blocked_by_external_ids"], ["notion-project-blocker"])
        self.assertEqual(parsed["source_updated_at"], "2026-07-18T01:00:00.000Z")

    def test_task_parser_preserves_project_assignees_and_hierarchy(self) -> None:
        parsed = notion_client.parse_task_page(self.task_page())
        self.assertEqual(parsed["project_external_id"], "notion-project-petit")
        self.assertEqual(parsed["project_external_ids"], ["notion-project-petit"])
        self.assertEqual(parsed["assignee_external_ids"], ["notion-user-soso", "notion-user-helper"])
        self.assertEqual(parsed["parent_external_id"], "task-parent")
        self.assertEqual(parsed["subtask_external_ids"], ["task-child-a", "task-child-b"])
        self.assertEqual(parsed["summary"], "プロジェクトとタスクを同期する")

    def test_same_name_creates_candidate_but_does_not_auto_link(self) -> None:
        project_continuity.create_project("PETIT", project_id="petit")
        notion_project_sync.upsert_projects([notion_client.parse_project_page(self.project_page())])
        with db.get_connection() as conn:
            cached = conn.execute("SELECT internal_project_id FROM notion_projects_cache WHERE external_id='notion-project-petit'").fetchone()
            candidate = conn.execute("SELECT project_id, status, suggested_project_ids FROM notion_source_candidates WHERE external_id='notion-project-petit'").fetchone()
        self.assertIsNone(cached["internal_project_id"])
        self.assertIsNone(candidate["project_id"])
        self.assertEqual(candidate["status"], "pending")
        self.assertEqual(json.loads(candidate["suggested_project_ids"]), ["petit"])

    def test_candidate_link_tool_confirms_mapping_and_remaps_tasks(self) -> None:
        project_continuity.create_project("PETIT", project_id="petit")
        notion_project_sync.upsert_projects([notion_client.parse_project_page(self.project_page())])
        notion_project_sync.upsert_tasks([notion_client.parse_task_page(self.task_page())])
        candidate = notion_project_links.list_candidates()[0]
        self.assertTrue(tools.requires_confirmation("link_notion_project_candidate"))
        result = json.loads(tools.dispatch("link_notion_project_candidate", {"candidate_id": candidate["id"], "project_id": "petit"}))
        self.assertTrue(result["linked"])
        self.assertIsNotNone(result["source_link"]["confirmed_at"])
        with db.get_connection() as conn:
            task = conn.execute("SELECT project_id FROM tasks_cache WHERE external_id='task-a'").fetchone()
            source = conn.execute("SELECT project_id, status, confirmed_at FROM project_source_links WHERE provider='notion' AND external_id='notion-project-petit'").fetchone()
            candidate_row = conn.execute("SELECT status, project_id FROM notion_source_candidates WHERE id=?", (candidate["id"],)).fetchone()
        self.assertEqual(task["project_id"], "petit")
        self.assertEqual(source["project_id"], "petit")
        self.assertEqual(source["status"], "active")
        self.assertIsNotNone(source["confirmed_at"])
        self.assertEqual(candidate_row["status"], "linked")
        self.assertEqual(candidate_row["project_id"], "petit")

    def test_confirmed_source_link_resolves_project_and_task(self) -> None:
        project_continuity.create_project("PETIT", project_id="petit")
        project_continuity.link_project_source("petit", "notion", "notion-project-petit", external_url="https://notion.so/notion-project-petit", confirmed=True)
        notion_project_sync.upsert_projects([notion_client.parse_project_page(self.project_page())])
        notion_project_sync.upsert_tasks([notion_client.parse_task_page(self.task_page())])
        with db.get_connection() as conn:
            project = conn.execute("SELECT internal_project_id FROM notion_projects_cache WHERE external_id='notion-project-petit'").fetchone()
            task = conn.execute("SELECT project_id, project_external_id, assignee_external_ids, parent_external_id, subtask_external_ids, summary FROM tasks_cache WHERE external_id='task-a'").fetchone()
        self.assertEqual(project["internal_project_id"], "petit")
        self.assertEqual(task["project_id"], "petit")
        self.assertEqual(task["project_external_id"], "notion-project-petit")
        self.assertEqual(json.loads(task["assignee_external_ids"]), ["notion-user-soso", "notion-user-helper"])
        self.assertEqual(task["parent_external_id"], "task-parent")
        self.assertEqual(json.loads(task["subtask_external_ids"]), ["task-child-a", "task-child-b"])
        self.assertEqual(task["summary"], "プロジェクトとタスクを同期する")

    def test_unconfirmed_relation_never_populates_internal_task_project(self) -> None:
        project_continuity.create_project("PETIT", project_id="petit")
        notion_project_sync.upsert_projects([notion_client.parse_project_page(self.project_page())])
        notion_project_sync.upsert_tasks([notion_client.parse_task_page(self.task_page())])
        with db.get_connection() as conn:
            task = conn.execute("SELECT project_id, project_external_id FROM tasks_cache WHERE external_id='task-a'").fetchone()
        self.assertIsNone(task["project_id"])
        self.assertEqual(task["project_external_id"], "notion-project-petit")

    def test_partial_failure_keeps_project_cache_and_replaces_successful_task_source(self) -> None:
        first = notion_project_sync.sync_all_if_configured(force=True, project_loader=lambda: [notion_client.parse_project_page(self.project_page())], task_loader=lambda: [notion_client.parse_task_page(self.task_page("task-a"))])
        self.assertTrue(first["ok"])

        def project_failure() -> list[dict]:
            raise NotionError("projects unavailable")

        second = notion_project_sync.sync_all_if_configured(force=True, project_loader=project_failure, task_loader=lambda: [notion_client.parse_task_page(self.task_page("task-b"))])
        self.assertFalse(second["ok"])
        self.assertTrue(second["partial"])
        self.assertTrue(second["sources"]["projects"]["stale"])
        self.assertTrue(second["sources"]["projects"]["cached"])
        self.assertTrue(second["sources"]["tasks"]["ok"])
        with db.get_connection() as conn:
            project_count = conn.execute("SELECT COUNT(*) FROM notion_projects_cache").fetchone()[0]
            task_ids = {row["external_id"] for row in conn.execute("SELECT external_id FROM tasks_cache WHERE source='notion'").fetchall()}
        self.assertEqual(project_count, 1)
        self.assertEqual(task_ids, {"task-b"})

    def test_resume_aggregates_notion_project_and_task_freshness(self) -> None:
        project_continuity.create_project("PETIT", project_id="petit")
        project_continuity.link_project_source("petit", "notion", "notion-project-petit", confirmed=True)
        db.record_sync_success("notion:projects", 1)
        db.record_sync_success("notion:tasks", 2)
        db.record_sync_failure("notion:projects", "project API timeout")
        context = project_resume.build_resume_context("soso", "petit")
        rendered = project_resume.render_resume_message(context)
        self.assertTrue(context.source_freshness["notion"]["stale"])
        self.assertIn("notion:projects", context.source_freshness["notion"]["sources"])
        self.assertIn("notion:tasks", context.source_freshness["notion"]["sources"])
        self.assertIn("notionは最新同期に失敗", rendered)

    def test_legacy_flat_task_page_stays_parseable(self) -> None:
        page = self.task_page("legacy-task")
        for key in ("プロジェクト", "担当者", "親タスク", "サブタスク", "要約"):
            page["properties"].pop(key)
        parsed = notion_client._parse_page(page)
        self.assertEqual(parsed["title"], "Notion Adapter v2を実装")
        self.assertEqual(parsed["project_external_ids"], [])
        self.assertEqual(parsed["assignee_external_ids"], [])
        self.assertIsNone(parsed["parent_external_id"])


if __name__ == "__main__":
    unittest.main()
