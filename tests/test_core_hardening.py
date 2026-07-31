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
            return {"role": "assistant", "content": "設計を分析しました", "tool_calls": []}

        route = {
            "type": "agent",
            "capabilities": [],
            "goal": "設計を分析する",
            "source": "test",
            "confidence": 1.0,
        }
        with (
            patch.object(agent.project_router, "try_handle_project_turn", return_value=None),
            patch.object(agent.model_router, "choose", return_value=route),
            patch.object(config, "CHAT_MODEL", "chat-test"),
            patch.object(config, "AGENT_MODEL", "agent-test"),
            patch.object(agent, "chat_completion", side_effect=fake_chat),
        ):
            result = agent.run("このPython設計を分析して改善点をレビューして")

        self.assertEqual(calls, [{"tools": None, "model": "agent-test", "route": "agent"}])
        self.assertEqual(result["model_route"]["requested_route"], "agent")
        self.assertEqual(result["model_route"]["actual_route"], "agent")
        self.assertEqual(result["model_route"]["router_source"], "test")

    def test_time_stays_deterministic_and_greeting_uses_agent(self) -> None:
        route = {
            "type": "agent",
            "capabilities": [],
            "goal": "自然に挨拶へ返答する",
            "source": "test",
            "confidence": 1.0,
        }
        with (
            patch.object(agent.project_router, "try_handle_project_turn", return_value=None),
            patch.object(agent.model_router, "choose", return_value=route) as router,
            patch.object(
                agent.tools,
                "dispatch",
                return_value=json.dumps(
                    {
                        "ok": True,
                        "time": "10:30",
                        "date": "2026-07-22",
                        "weekday": "水曜日",
                        "timezone": "Asia/Tokyo",
                    },
                    ensure_ascii=False,
                ),
            ),
            patch.object(
                agent,
                "chat_completion",
                return_value={"role": "assistant", "content": "やっほー。今日はどうする？", "tool_calls": []},
            ),
        ):
            time_result = agent.run("今何時？")
            greeting_result = agent.run("やっほー")

        router.assert_called_once_with("やっほー", [])
        self.assertIn("10:30", time_result["reply"])
        self.assertEqual(time_result["model_route"]["actual_route"], "deterministic")
        self.assertEqual(greeting_result["model_route"]["actual_route"], "agent")
        self.assertIn("やっほー", greeting_result["reply"])

    def test_capability_tool_is_executed_with_compressed_user_context(self) -> None:
        calls: list[dict[str, object]] = []
        dispatched: list[tuple[str, object]] = []
        route = {
            "type": "agent",
            "capabilities": ["calendar"],
            "goal": "東京の天気から傘が必要か判断する",
            "source": "llm",
            "confidence": 0.95,
        }

        def fake_chat(messages, tools=None, temperature=None, model=None, max_tokens=None, route="chat"):
            calls.append({"messages": messages, "tools": tools, "model": model, "route": route})
            if len(calls) == 1:
                return {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "weather-1",
                            "type": "function",
                            "function": {"name": "get_weather", "arguments": '{"location":"東京"}'},
                        }
                    ],
                }
            return {"role": "assistant", "content": "傘を持っていくのが安全です。", "tool_calls": []}

        def fake_dispatch(name, arguments):
            dispatched.append((name, arguments))
            return json.dumps({"ok": True, "forecast": "rain", "raw": "transport noise"}, ensure_ascii=False)

        with (
            patch.object(agent.project_router, "try_handle_project_turn", return_value=None),
            patch.object(agent.model_router, "choose", return_value=route),
            patch.object(config, "CHAT_MODEL", "chat-test"),
            patch.object(config, "AGENT_MODEL", "agent-test"),
            patch.object(agent, "chat_completion", side_effect=fake_chat),
            patch.object(agent.tools, "dispatch", side_effect=fake_dispatch),
        ):
            result = agent.run("傘を持っていくべき？")

        self.assertEqual([name for name, _ in dispatched], ["get_weather"])
        self.assertEqual([item["name"] for item in result["used_tools"]], ["get_weather"])
        second_messages = calls[1]["messages"]
        self.assertEqual(second_messages[-1]["role"], "user")
        self.assertIn("元の依頼", second_messages[-1]["content"])
        self.assertIn("圧縮結果", second_messages[-1]["content"])
        self.assertNotIn("transport noise", second_messages[-1]["content"])

    def test_multiple_tool_rounds_allow_same_tool_with_different_arguments(self) -> None:
        dispatched: list[dict[str, object]] = []
        call_count = 0
        route = {
            "type": "agent",
            "capabilities": ["calendar"],
            "goal": "直近2日を比較する",
            "source": "llm",
            "confidence": 0.9,
        }

        def fake_chat(messages, tools=None, temperature=None, model=None, max_tokens=None, route="chat"):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                target = f"2026-07-{21 + call_count:02d}"
                return {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": f"schedule-{call_count}",
                            "type": "function",
                            "function": {"name": "get_schedule", "arguments": json.dumps({"date": target})},
                        }
                    ],
                }
            return {"role": "assistant", "content": "2日分を比較しました。", "tool_calls": []}

        def fake_dispatch(name, arguments):
            dispatched.append(dict(arguments))
            return json.dumps({"ok": True, "date": arguments["date"], "events": []})

        with (
            patch.object(agent.project_router, "try_handle_project_turn", return_value=None),
            patch.object(agent.model_router, "choose", return_value=route),
            patch.object(config, "MAX_TOOL_ITERATIONS", 2),
            patch.object(agent, "chat_completion", side_effect=fake_chat),
            patch.object(agent.tools, "dispatch", side_effect=fake_dispatch),
        ):
            result = agent.run("直近2日で空いている日を比べて")

        self.assertEqual([item["date"] for item in dispatched], ["2026-07-22", "2026-07-23"])
        self.assertEqual(call_count, 3)
        self.assertEqual(result["reply"], "2日分を比較しました。")
        self.assertEqual(result["model_route"]["tool_rounds"], 2)

    def test_agent_prompt_allows_complete_analysis(self) -> None:
        self.assertIn("十分な長さ", agent.AGENT_SYSTEM_PROMPT)
        self.assertIn("結論", agent.AGENT_SYSTEM_PROMPT)
        self.assertNotIn("1〜2文", agent.AGENT_SYSTEM_PROMPT)

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
