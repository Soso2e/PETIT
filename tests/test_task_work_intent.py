from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from backend import agent, config, db, notion_task_sync, project_continuity, task_work_intent, work_sessions


class TaskWorkIntentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(config, "DB_PATH", Path(self.temp.name) / "app.db")
        self.db_patch.start()
        db.init_db()
        notion_task_sync.ensure_schema()
        self.llm_patch = patch("backend.brain_runtime.run", side_effect=AssertionError("LLM must not run"))
        self.llm_patch.start()

    def tearDown(self) -> None:
        self.llm_patch.stop()
        self.db_patch.stop()
        self.temp.cleanup()

    def add_task(self, title: str = "HERE", status: str = "Yet", *, deleted: bool = False) -> str:
        with db.get_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO tasks_cache(source, title, status, updated_at, remote_deleted_at) VALUES ('notion', ?, ?, ?, ?)",
                (title, status, db.now_iso(), db.now_iso() if deleted else None),
            )
            return str(cursor.lastrowid)

    def test_reported_variants_resume_same_paused_session_and_repeated_input_is_idempotent(self) -> None:
        task_id = self.add_task()
        now = datetime.now(timezone.utc)
        work_sessions.start_session("original", "HERE", task_id=task_id, now=now - timedelta(minutes=20))
        work_sessions.pause_session("original", now=now - timedelta(minutes=10))
        for message in ("HERE再開", "HEREタスク再開", "HEREタスク再開", "HERE作業再開"):
            with self.subTest(message=message):
                result = agent.run(message)
                self.assertNotIn("プロジェクト台帳", result["reply"])
                self.assertEqual(result["used_tools"][0]["name"], "start_work_session")
                self.assertNotIn("pending_actions", result)
                active = work_sessions.active_session()
                self.assertEqual(active["session_id"], "original")
                self.assertEqual(active["status"], "active")
                self.assertGreaterEqual(active["elapsed_seconds"], 600)
                self.assertLess(active["elapsed_seconds"], 620)
        with db.get_connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM work_sessions").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM work_session_events WHERE event_type='resumed'").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT status FROM tasks_cache WHERE id=?", (task_id,)).fetchone()[0], "Yet")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0], 0)

    def test_variants_start_existing_task_without_session(self) -> None:
        task_id = self.add_task()
        for message in ("HERE再開", "HEREタスクを再開", "HEREの作業を再開する", "HERE タスク 再開して", "今から 「HERE」のタスクを再開してください", "ＨＥＲＥ作業再開！"):
            with self.subTest(message=message):
                result = agent.run(message)
                self.assertIn("HERE", result["reply"])
                self.assertEqual(work_sessions.active_session()["task_id"], task_id)
                work_sessions.end_session(work_sessions.active_session()["session_id"])

    def test_ended_session_is_preserved_when_new_measurement_starts(self) -> None:
        task_id = self.add_task()
        work_sessions.start_session("old", "HERE", task_id=task_id)
        work_sessions.end_session("old")
        before = work_sessions._row("old")
        agent.run("HERE再開")
        self.assertEqual(work_sessions._row("old"), before)
        self.assertNotEqual(work_sessions.active_session()["session_id"], "old")

    def test_switching_tasks_ends_previous_session_and_preserves_history(self) -> None:
        other = self.add_task("OTHER")
        here = self.add_task()
        work_sessions.start_session("other", "OTHER", task_id=other)
        agent.run("HERE再開")
        self.assertEqual(work_sessions.active_session()["task_id"], here)
        self.assertEqual(work_sessions._row("other")["status"], "ended")

    def test_exact_title_wins_over_suffix_stripping_and_partial_matches(self) -> None:
        self.add_task("HERE")
        literal = self.add_task("HEREタスク")
        self.add_task("HEREタスク追加")
        agent.run("HEREタスク再開")
        self.assertEqual(work_sessions.active_session()["task_id"], literal)

    def test_stripped_exact_title_wins_over_partial_raw_query(self) -> None:
        here = self.add_task()
        self.add_task("HEREタスク追加")
        agent.run("HEREタスク再開")
        self.assertEqual(work_sessions.active_session()["task_id"], here)

    def test_unique_partial_task_match(self) -> None:
        here = self.add_task("HEREの素材制作")
        agent.run("HERE作業再開")
        self.assertEqual(work_sessions.active_session()["task_id"], here)

    def test_multiple_matches_do_not_replace_current_work_or_create_project(self) -> None:
        self.add_task("HERE A")
        self.add_task("HERE B")
        work_sessions.start_session("original", "別の作業")
        for message in ("HERE再開", "HEREタスク再開", "HERE作業再開"):
            with self.subTest(message=message):
                result = agent.run(message)
                self.assertIn("候補が複数", result["reply"])
                self.assertIn("HERE A", result["reply"])
                self.assertIn("HERE B", result["reply"])
                self.assertEqual(result["used_tools"], [])
                self.assertEqual(work_sessions.active_session()["session_id"], "original")

    def test_unavailable_explicit_tasks_do_not_fall_through_to_project_registration(self) -> None:
        self.add_task("DONE", config.NOTION_DONE_STATUS)
        self.add_task("DELETED", deleted=True)
        self.add_task("CANCELLED", "cancelled")
        for title in ("MISSING", "DONE", "DELETED", "CANCELLED"):
            with self.subTest(title=title):
                result = agent.run(f"{title}タスク再開")
                self.assertIn("未完了タスクが見つかりません", result["reply"])
                self.assertNotIn("pending_actions", result)
                self.assertIsNone(work_sessions.active_session())

    def test_project_only_and_unknown_bare_name_preserve_project_routes(self) -> None:
        project_continuity.create_project("PETIT", project_id="petit")
        result = agent.run("PETIT再開")
        self.assertEqual(result["model_route"]["kind"], "project_continuity")
        result = agent.run("UNKNOWN再開")
        self.assertIn("プロジェクト台帳", result["reply"])

    def test_explicit_project_wins_and_bare_collision_requires_disambiguation(self) -> None:
        self.add_task()
        project_continuity.create_project("HERE", project_id="here-project")
        result = agent.run("HERE再開")
        self.assertIn("両方に一致", result["reply"])
        self.assertIsNone(work_sessions.active_session())
        self.assertIsNone(project_continuity.get_active_project(config.PETIT_OWNER_ID))
        result = agent.run("HEREプロジェクト再開")
        self.assertEqual(result["model_route"]["kind"], "project_continuity")
        self.assertIsNone(work_sessions.active_session())
        agent.run("HEREタスク再開")
        self.assertEqual(work_sessions.active_session()["task"], "HERE")

    def test_questions_and_ordinary_chat_are_not_resume_commands(self) -> None:
        self.add_task()
        for text in ("セッションは?", "どういうこと？", "HEREタスクはある？", "HEREを再開するには？", "HERE再開できる？", "HERE再開しない", "再開", "こんにちは"):
            with self.subTest(text=text):
                self.assertIsNone(task_work_intent.try_handle(text))
                self.assertIsNone(work_sessions.active_session())

    def test_dispatch_failure_is_not_reported_as_resumed(self) -> None:
        self.add_task()
        for raw in ('[error] failed', '{}', '{"started": false}', '{"started": true, "session": {"status": "paused"}}'):
            with self.subTest(raw=raw), patch("backend.task_work_intent.tools.dispatch", return_value=raw):
                result = agent.run("HEREタスク再開")
                self.assertFalse(result["persist"])
                self.assertNotIn("再開しました", result["reply"])
                self.assertIsNone(work_sessions.active_session())

    def test_missing_task_name_does_not_fuzzily_start_a_task(self) -> None:
        self.add_task("唯一のタスク")
        result = agent.run("タスク再開")
        self.assertIn("タスク名を指定", result["reply"])
        self.assertIsNone(work_sessions.active_session())

    def test_http_chat_resumes_and_persists_without_llm_or_pending_approval(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from backend import chat

        task_id = self.add_task()
        work_sessions.start_session("api-original", "HERE", task_id=task_id)
        work_sessions.pause_session("api-original")
        app = FastAPI()
        app.include_router(chat.router)
        with patch.object(chat._artifact_executor, "submit"), TestClient(app) as client:
            for index, text in enumerate(("HERE再開", "HEREタスク再開", "HERE作業再開")):
                response = client.post("/api/chat", json={
                    "message": text, "session_id": "resume-chat", "request_id": f"resume-{index}",
                })
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertFalse(payload.get("error"))
                self.assertEqual(payload["pending_actions"], [])
                self.assertEqual(payload["request_id"], f"resume-{index}")
                self.assertEqual(payload["used_tools"][0]["name"], "start_work_session")
                self.assertEqual(payload["model_route"]["observability"]["llm_calls"], 0)
        self.assertEqual(work_sessions.active_session()["session_id"], "api-original")
        with db.get_connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM conversations WHERE session_id='resume-chat'").fetchone()[0], 3)


if __name__ == "__main__":
    unittest.main()
