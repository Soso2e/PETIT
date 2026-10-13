from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import config, db, notion_client, task_sync_queue
from backend.notion_client import NotionError
from backend.tools import tasks_phase2


def remote_task(
    *,
    external_id: str = "notion-task-1",
    title: str = "タスク",
    status: str = "Yet",
    due_date: str | None = None,
    priority: str = "Mid",
    source_updated_at: str = "2026-07-21T10:00:00.000Z",
) -> dict[str, object]:
    return {
        "external_id": external_id,
        "title": title,
        "status": status,
        "due_date": due_date,
        "priority": priority,
        "category": None,
        "area": "personal",
        "reason": None,
        "url": f"https://notion.so/{external_id}",
        "done_date": None,
        "project_external_ids": [],
        "assignee_external_ids": [],
        "parent_external_ids": [],
        "subtask_external_ids": [],
        "summary": None,
        "source_updated_at": source_updated_at,
    }


class TaskWriteQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(config, "DB_PATH", Path(self.tmp.name) / "petit.sqlite3")
        self.db_patch.start()
        db.init_db()
        task_sync_queue.ensure_task_sync_schema()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.tmp.cleanup()

    def _task(self, task_id: int) -> dict[str, object]:
        with db.get_connection() as conn:
            row = conn.execute("SELECT * FROM tasks_cache WHERE id=?", (task_id,)).fetchone()
        self.assertIsNotNone(row)
        return dict(row)

    def _operations(self, task_id: int) -> list[dict[str, object]]:
        return task_sync_queue.status(task_id=task_id)["operations"]

    def test_create_saves_locally_and_queues_notion_immediately(self) -> None:
        with patch.object(config, "notion_configured", return_value=True):
            result = tasks_phase2.create_task("提出資料を作る", area="university", priority="High")

        self.assertTrue(result["created"])
        self.assertTrue(result["queued"])
        task_id = int(result["task"]["id"])
        cached = self._task(task_id)
        self.assertEqual(cached["source"], "notion")
        self.assertEqual(cached["sync_status"], "pending")
        self.assertIsNone(cached["external_id"])
        operations = self._operations(task_id)
        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0]["operation"], "create")
        self.assertEqual(operations[0]["status"], "pending")

    def test_successful_create_updates_same_local_row_to_synced(self) -> None:
        with patch.object(config, "notion_configured", return_value=True):
            result = tasks_phase2.create_task("提出資料を作る", area="university")
        task_id = int(result["task"]["id"])
        synced = remote_task(external_id="remote-1", title="提出資料を作る")

        with patch.object(task_sync_queue, "create_task_page", return_value=synced):
            self.assertTrue(task_sync_queue.process_next())

        cached = self._task(task_id)
        self.assertEqual(cached["id"], task_id)
        self.assertEqual(cached["external_id"], "remote-1")
        self.assertEqual(cached["sync_status"], "synced")
        self.assertIsNotNone(cached["last_synced_at"])
        self.assertEqual(self._operations(task_id)[0]["status"], "synced")

    def test_failure_is_visible_and_manual_retry_can_succeed(self) -> None:
        with patch.object(config, "notion_configured", return_value=True):
            result = tasks_phase2.create_task("同期失敗テスト")
        task_id = int(result["task"]["id"])

        with patch.object(task_sync_queue, "create_task_page", side_effect=NotionError("offline")):
            self.assertTrue(task_sync_queue.process_next())
        failed = self._task(task_id)
        self.assertEqual(failed["sync_status"], "failed")
        self.assertIn("offline", str(failed["sync_error"]))

        retry = tasks_phase2.retry_task_sync(task_id)
        self.assertTrue(retry["queued"])
        with patch.object(
            task_sync_queue,
            "create_task_page",
            return_value=remote_task(external_id="remote-retry", title="同期失敗テスト"),
        ):
            self.assertTrue(task_sync_queue.process_next())
        self.assertEqual(self._task(task_id)["sync_status"], "synced")

    def test_update_is_optimistic_then_synced_in_background(self) -> None:
        task_sync_queue.upsert_tasks_with_conflict_guard(
            [remote_task(external_id="remote-update", title="編集前", due_date="2026-07-22")]
        )
        with db.get_connection() as conn:
            task_id = int(conn.execute("SELECT id FROM tasks_cache WHERE external_id='remote-update'").fetchone()[0])

        result = tasks_phase2.update_task(task_id=task_id, title="編集後", due_date="2026-07-30")
        self.assertTrue(result["updated"])
        self.assertEqual(self._task(task_id)["title"], "編集後")
        self.assertEqual(self._task(task_id)["sync_status"], "pending")

        updated_remote = remote_task(
            external_id="remote-update",
            title="編集後",
            due_date="2026-07-30",
            source_updated_at="2026-07-21T11:00:00.000Z",
        )
        with patch.object(task_sync_queue, "_update_remote_task", return_value=updated_remote), patch.object(
            task_sync_queue.notion_client, "get_task_page", return_value=remote_task(external_id="remote-update")
        ):
            self.assertTrue(task_sync_queue.process_next())
        cached = self._task(task_id)
        self.assertEqual(cached["title"], "編集後")
        self.assertEqual(cached["due_date"], "2026-07-30")
        self.assertEqual(cached["sync_status"], "synced")

    def test_remote_change_marks_conflict_without_overwriting_local_edit(self) -> None:
        task_sync_queue.upsert_tasks_with_conflict_guard(
            [remote_task(external_id="remote-conflict", title="競合", due_date="2026-07-22")]
        )
        with db.get_connection() as conn:
            task_id = int(conn.execute("SELECT id FROM tasks_cache WHERE external_id='remote-conflict'").fetchone()[0])

        tasks_phase2.update_task(task_id=task_id, due_date="2026-07-30")
        task_sync_queue.upsert_tasks_with_conflict_guard(
            [
                remote_task(
                    external_id="remote-conflict",
                    title="Notion側の変更",
                    due_date="2026-07-25",
                    source_updated_at="2026-07-21T12:00:00.000Z",
                )
            ]
        )

        cached = self._task(task_id)
        self.assertEqual(cached["title"], "競合")
        self.assertEqual(cached["due_date"], "2026-07-30")
        self.assertEqual(cached["sync_status"], "conflict")
        detail = tasks_phase2.get_task_sync_status(task_id)
        self.assertEqual(detail["task"]["remote_snapshot"]["title"], "Notion側の変更")
        self.assertFalse(tasks_phase2.retry_task_sync(task_id)["queued"])

    def test_explicit_edit_after_conflict_uses_acknowledged_remote_revision(self) -> None:
        task_sync_queue.upsert_tasks_with_conflict_guard(
            [remote_task(external_id="remote-resolve", title="元", source_updated_at="2026-07-21T10:00:00.000Z")]
        )
        with db.get_connection() as conn:
            task_id = int(conn.execute("SELECT id FROM tasks_cache WHERE external_id='remote-resolve'").fetchone()[0])
        tasks_phase2.update_task(task_id=task_id, title="ローカル編集")
        task_sync_queue.upsert_tasks_with_conflict_guard(
            [remote_task(external_id="remote-resolve", title="Notion編集", source_updated_at="2026-07-21T12:00:00.000Z")]
        )

        result = tasks_phase2.update_task(task_id=task_id, title="確認後の確定値")
        self.assertTrue(result["queued"])
        self.assertEqual(self._task(task_id)["source_updated_at"], "2026-07-21T12:00:00.000Z")
        resolved_remote = remote_task(
            external_id="remote-resolve",
            title="確認後の確定値",
            source_updated_at="2026-07-21T13:00:00.000Z",
        )
        with patch.object(task_sync_queue, "_update_remote_task", return_value=resolved_remote), patch.object(
            task_sync_queue.notion_client, "get_task_page", return_value=remote_task(external_id="remote-resolve", source_updated_at="2026-07-21T12:00:00.000Z")
        ):
            self.assertTrue(task_sync_queue.process_next())
        self.assertEqual(self._task(task_id)["sync_status"], "synced")
        self.assertEqual(self._task(task_id)["title"], "確認後の確定値")

    def test_edit_before_create_sync_is_coalesced_into_single_create(self) -> None:
        with patch.object(config, "notion_configured", return_value=True):
            result = tasks_phase2.create_task("作成前", due_date="2026-07-22")
        task_id = int(result["task"]["id"])
        tasks_phase2.update_task(task_id=task_id, title="作成前に編集", due_date="2026-08-01")

        with db.get_connection() as conn:
            rows = conn.execute("SELECT operation, payload_json FROM task_sync_queue WHERE task_id=?", (task_id,)).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["operation"], "create")
        payload = json.loads(rows[0]["payload_json"])
        self.assertEqual(payload["title"], "作成前に編集")
        self.assertEqual(payload["due_date"], "2026-08-01")

    def test_complete_task_queues_notion_update(self) -> None:
        task_sync_queue.upsert_tasks_with_conflict_guard(
            [remote_task(external_id="remote-complete", title="完了する")]
        )
        with db.get_connection() as conn:
            task_id = int(conn.execute("SELECT id FROM tasks_cache WHERE external_id='remote-complete'").fetchone()[0])
        result = tasks_phase2.complete_task(task_id=task_id, done_date="2026-07-21")
        self.assertTrue(result["completed"])
        cached = self._task(task_id)
        self.assertEqual(cached["status"], config.NOTION_DONE_STATUS)
        self.assertEqual(cached["done_date"], "2026-07-21")
        self.assertEqual(cached["sync_status"], "pending")

    def test_local_task_update_does_not_create_notion_operation(self) -> None:
        with patch.object(config, "notion_configured", return_value=False):
            created = tasks_phase2.create_task("ローカルタスク", area="personal")
        task_id = int(created["task"]["id"])
        result = tasks_phase2.update_task(task_id=task_id, priority="High")
        self.assertTrue(result["updated"])
        self.assertEqual(result["sync_status"], "synced")
        self.assertEqual(self._operations(task_id), [])

    def test_update_task_rejects_invalid_status_values(self) -> None:
        """不正なstatus指定（MidやHighなど）をupdate_taskが弾くことを検証する。"""
        with patch.object(config, "notion_configured", return_value=False):
            created = tasks_phase2.create_task("ステータステストタスク", area="personal")
        task_id = int(created["task"]["id"])

        # priorityの値（MidやHigh）がstatusとして誤って渡された場合に弾かれること
        invalid_candidates = ["Mid", "High", "Low", "UnknownStatus", "123"]
        for invalid_status in invalid_candidates:
            result = tasks_phase2.update_task(task_id=task_id, status=invalid_status)
            self.assertFalse(result["updated"])
            self.assertIn("statusは", result["error"])

    def test_update_task_accepts_and_normalizes_valid_status(self) -> None:
        """有効なstatusおよびエイリアスが正しく正規化されて更新されることを検証する。"""
        with patch.object(config, "notion_configured", return_value=False):
            created = tasks_phase2.create_task("ステータス正規化タスク", area="personal")
        task_id = int(created["task"]["id"])

        # 有効なステータス "Now"
        result_now = tasks_phase2.update_task(task_id=task_id, status="Now")
        self.assertTrue(result_now["updated"])
        self.assertEqual(result_now["task"]["status"], "Now")

        # 日本語エイリアス "完了" -> "Done"
        result_done = tasks_phase2.update_task(task_id=task_id, status="完了")
        self.assertTrue(result_done["updated"])
        self.assertEqual(result_done["task"]["status"], "Done")

        # 小文字 "chancel" -> "Chancel"
        result_cancel = tasks_phase2.update_task(task_id=task_id, status="chancel")
        self.assertTrue(result_cancel["updated"])
        self.assertEqual(result_cancel["task"]["status"], "Chancel")

    def test_create_task_with_immediate_rename_and_parent_sync(self) -> None:
        """タスク作成直後に名前変更や親タスク情報が付与されてもNotion作成同期が失敗しないことを検証する。"""
        with patch.object(config, "notion_configured", return_value=True):
            created = tasks_phase2.create_task("新規タスク", area="personal")
            task_id = int(created["task"]["id"])

            # 作成直後（Notion同期前）に名前を変更
            rename_result = tasks_phase2.update_task(task_id=task_id, title="即時変更タスク")
            self.assertTrue(rename_result["updated"])

            # キューに親タスク情報がマージされた状態をシミュレート
            task_sync_queue.enqueue_update(task_id, {"parent_external_ids": ["parent-page-999"]}, base_source_updated_at=None)

            # キューの create 操作の payload に parent_external_ids が含まれていることを確認
            with db.get_connection() as conn:
                op_row = conn.execute("SELECT operation, payload_json FROM task_sync_queue WHERE task_id=? AND operation='create'", (task_id,)).fetchone()
            self.assertIsNotNone(op_row)
            payload = json.loads(op_row["payload_json"])
            self.assertIn("parent_external_ids", payload)
            self.assertEqual(payload["title"], "即時変更タスク")

            # create_task_pageがparent_external_idsを受け取ってエラーなく正常終了すること
            dummy_remote = remote_task(external_id="notion-page-created", title=payload["title"])
            with patch("backend.task_sync_queue.create_task_page", return_value=dummy_remote) as mock_create:
                processed = task_sync_queue.process_next()
                self.assertTrue(processed)
                mock_create.assert_called_once()
                self.assertIn("parent_external_ids", mock_create.call_args.kwargs)

            # タスクが同期済み（synced）になり、external_idが保存されたことを確認
            synced_task = self._task(task_id)
            self.assertEqual(synced_task["sync_status"], "synced")
            self.assertEqual(synced_task["external_id"], "notion-page-created")
            self.assertEqual(synced_task["title"], "即時変更タスク")

    def test_notion_client_create_task_page_supports_parent_external_ids(self) -> None:
        """notion_client.create_task_pageがparent_external_idsをプロパティへ変換することを検証する。"""
        fake_page = {
            "id": "new-page-id",
            "last_edited_time": "2026-10-14T00:00:00.000Z",
            "url": "https://notion.so/new-page-id",
            "properties": {},
        }
        with patch("backend.notion_client._post", return_value=fake_page) as mock_post, \
             patch("backend.notion_client.parse_task_page", return_value={"id": "new-page-id", "external_id": "new-page-id"}):
            notion_client.create_task_page(
                title="子タスク",
                parent_external_ids=["parent-ext-1"],
                area="personal",
                extra_unknown_field="ignored_safely",
            )
            mock_post.assert_called_once()
            called_body = mock_post.call_args[0][1]
            parent_prop = called_body["properties"].get(config.NOTION_TASK_PROP_PARENT)
            self.assertIsNotNone(parent_prop)
            self.assertEqual(parent_prop["relation"], [{"id": "parent-ext-1"}])


if __name__ == "__main__":
    unittest.main()


