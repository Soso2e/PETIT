from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import agent, briefing, config, db, main, notion_project_sync, request_context, summarizer


class RoutingAndMemoryHardeningTests(unittest.TestCase):
    def test_pure_reasoning_uses_agent_endpoint_without_tools(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_chat(messages, tools=None, temperature=None, model=None, max_tokens=None, route="chat"):
            calls.append({"tools": tools, "model": model, "route": route})
            return {"role": "assistant", "content": "設計を分析しました"}

        with (
            patch.object(agent.project_router, "try_handle_project_turn", return_value=None),
            patch.object(config, "CHAT_MODEL", "chat-test"),
            patch.object(config, "AGENT_MODEL", "agent-test"),
            patch.object(agent, "chat_completion", side_effect=fake_chat),
        ):
            result = agent.run("このPython設計を分析して改善点をレビューして")

        self.assertEqual(calls, [{"tools": None, "model": "agent-test", "route": "agent"}])
        self.assertEqual(result["model_route"]["requested_route"], "agent")
        self.assertEqual(result["model_route"]["actual_route"], "agent")
        self.assertIn("tools_or_reasoning", result["model_route"]["reasons"])

    def test_episode_summarizer_calls_agent_endpoint(self) -> None:
        rows = [
            {
                "id": 1,
                "timestamp": "2026-07-19T00:00:00+00:00",
                "user_text": "PETITの設計を直す",
                "assistant_text": "ルーターを統一する",
                "used_tools": None,
                "session_id": "s1",
            }
        ]
        valid = {
            "role": "assistant",
            "content": json.dumps(
                {
                    "title": "PETIT改善",
                    "summary": "モデルルーティングを統一する方針を決めた。",
                    "decisions": ["ルーターを一本化する"],
                    "facts": [],
                    "work_in_progress": ["回帰テストを追加中"],
                    "next_action": ["実モデルで確認する"],
                },
                ensure_ascii=False,
            ),
        }
        with (
            patch.object(summarizer.db, "pending_episode_groups", return_value=[rows]),
            patch.object(summarizer, "chat_completion", return_value=valid) as completion,
            patch.object(summarizer.db, "save_episode", return_value=7),
            patch.object(summarizer.markdown_export, "append_episode"),
            patch.object(summarizer.db, "save_memory_item", return_value=(1, False)),
            patch.object(summarizer.db, "all_memory", return_value=[]),
            patch.object(summarizer.db, "all_episodes", return_value=[]),
            patch.object(summarizer.chroma_client, "sync_structured_data", return_value={}),
        ):
            result = summarizer.summarize_pending(force=True)

        self.assertTrue(result["summarized"])
        self.assertEqual(completion.call_args.kwargs["route"], "agent")
        self.assertEqual(completion.call_args.kwargs["model"], config.AGENT_MODEL)

    def test_briefing_prefers_episode_context_over_legacy_summary(self) -> None:
        with (
            patch.object(briefing.db, "recent_episodes", return_value=[{"title": "PETIT", "summary": "Agent経路を修正した"}]),
            patch.object(briefing.db, "recent_summaries", return_value=[{"summary": "古い要約"}]) as legacy,
        ):
            context = briefing._recent_context(2)

        legacy.assert_not_called()
        self.assertEqual(context[0]["title"], "PETIT")
        self.assertEqual(context[0]["summary"], "Agent経路を修正した")


class PersistenceHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "petit.sqlite3"
        self.db_patch = patch.object(config, "DB_PATH", self.db_path)
        self.db_patch.start()
        db.init_db()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.tmp.cleanup()

    def test_sqlite_wal_busy_timeout_and_session_history(self) -> None:
        with db.get_connection() as conn:
            self.assertEqual(str(conn.execute("PRAGMA journal_mode").fetchone()[0]).casefold(), "wal")
            self.assertGreaterEqual(int(conn.execute("PRAGMA busy_timeout").fetchone()[0]), 5000)

        db.save_conversation("s1 user", "s1 reply", session_id="s1")
        db.save_conversation("s2 user", "s2 reply", session_id="s2")
        self.assertEqual([row["user_text"] for row in db.recent_conversations(session_id="s1")], ["s1 user"])

    def test_jobs_are_bound_to_session_and_acknowledged_explicitly(self) -> None:
        with request_context.bind(request_id="req-1", session_id="s1"):
            first = db.create_job("background_research", "{}")
        with request_context.bind(request_id="req-2", session_id="s2"):
            second = db.create_job("background_research", "{}")
        db.finish_job(first, "one")
        db.finish_job(second, "two")

        rows = main.jobs(limit=10, session_id="s1")["jobs"]
        self.assertEqual([row["id"] for row in rows], [first])
        # GET is read-only. The row remains available until explicit acknowledgement.
        self.assertEqual([row["id"] for row in main.jobs(limit=10, session_id="s1")["jobs"]], [first])

        acknowledged = main.acknowledge_jobs(main.JobAck(job_ids=[first], session_id="s1"))
        self.assertEqual(acknowledged["acknowledged"], 1)
        self.assertEqual(main.jobs(limit=10, session_id="s1")["jobs"], [])
        self.assertEqual([row["id"] for row in main.jobs(limit=10, session_id="s2")["jobs"]], [second])

    def test_successful_notion_task_sync_replaces_removed_rows(self) -> None:
        first = [
            {"external_id": "task-a", "title": "A", "status": "Yet"},
            {"external_id": "task-b", "title": "B", "status": "Yet"},
        ]
        notion_project_sync.upsert_tasks(first)
        notion_project_sync.upsert_tasks([{"external_id": "task-b", "title": "B updated", "status": "Now"}])

        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT external_id, title, status FROM tasks_cache WHERE source='notion' ORDER BY external_id"
            ).fetchall()
        self.assertEqual([dict(row) for row in rows], [{"external_id": "task-b", "title": "B updated", "status": "Now"}])


if __name__ == "__main__":
    unittest.main()
