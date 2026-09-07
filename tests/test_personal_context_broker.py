from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import brain_runtime, capability_router, config, context_broker as broker, db


class PersonalContextBrokerTests(unittest.TestCase):
    def collect(self, source, result, **need):
        with patch.object(broker, "_dispatch", return_value=result):
            return broker.collect({"needs": [{"source": source, **need}]})

    def test_web_personal_sources_keep_dates_status_and_provenance(self):
        results = {
            "memory": {"memories": [{"content": "朝に制作", "created_at": "2026-01-01", "raw": "PRIVATE"}], "episodes": []},
            "work": {"date": "2026-09-07", "total_seconds": 120, "tasks": [], "active": {"task": "PETIT", "status": "paused"}},
            "reminders": {"items": [{"id": 1, "title": "提出", "trigger_at": "2026-09-07T20:00:00+09:00", "status": "scheduled", "owner_id": "PRIVATE"}]},
            "brain": {"vault_notes": [{"text": "制作方針", "relative_path": "note.md", "source_path": "/PRIVATE/note.md"}]},
        }
        for source, result in results.items():
            with self.subTest(source=source):
                packet = self.collect(source, result)
                self.assertFalse(packet["partial"])
                self.assertNotIn("PRIVATE", broker.render_for_model(packet))
                self.assertTrue(packet["sources"][0]["facts"])
                self.assertIn("collected_at", packet["sources"][0])
        memory = self.collect("memory", results["memory"])["sources"][0]
        self.assertEqual(memory["freshness"]["status"], "historical")
        self.assertEqual(memory["facts"][0]["created_at"], "2026-01-01")

    def test_write_risk_is_rejected_before_dispatch(self):
        with patch.object(broker.tools, "risk_for", return_value="low_risk_write"), patch.object(broker.tools, "dispatch") as dispatch:
            result = broker._dispatch("work", {})
        self.assertEqual(result["error"], "read_boundary_violation")
        dispatch.assert_not_called()

    def test_search_requires_query_and_uses_fixed_read_tool(self):
        with patch.object(broker.tools, "dispatch", return_value='{"memories": [], "episodes": []}') as dispatch:
            self.assertEqual(broker._dispatch("memory", {})["error"], "query_required")
            dispatch.assert_not_called()
            broker._dispatch("memory", {"query": "制作", "tool": "save_memory"})
        dispatch.assert_called_once_with("search_memory", {"query": "制作", "limit": 5, "include_vault": False})

    def test_handoff_query_does_not_select_other_project_or_treat_wildcard_as_sql(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(config, "DB_PATH", Path(temp) / "test.db"):
            db.init_db()
            db.save_handoff_note("PETIT", "API", "テストする", None, None)
            db.save_handoff_note("映画", "視聴", "次を観る", None, None)
            result = broker._dispatch("handoff", {"query": "PETIT"})
            self.assertEqual([row["current_project"] for row in result["handoffs"]], ["PETIT"])
            self.assertEqual(broker._dispatch("handoff", {"query": "%"})["handoffs"], [])

    def test_malformed_or_missing_payload_is_not_empty_success(self):
        for value in ({}, {"items": "bad"}, {"items": ["bad"]}, []):
            with self.subTest(value=value):
                packet = self.collect("reminders", value)
                self.assertTrue(packet["partial"])
                self.assertEqual(packet["sources"][0]["facts"], [])
                self.assertEqual(packet["sources"][0]["error"], "invalid_tool_result")

    def test_partial_calendar_sync_and_stale_data_remain_visible(self):
        packet = self.collect("calendar", {"events": [{"title": "保存済み予定"}],
                              "calendar_sync": {"sources": [{"ok": True}, {"ok": False, "stale": True, "error": "PRIVATE"}]}})
        source = packet["sources"][0]
        self.assertTrue(packet["partial"])
        self.assertTrue(source["stale"])
        self.assertEqual(source["facts"][0]["title"], "保存済み予定")
        self.assertNotIn("PRIVATE", broker.render_for_model(packet))

    def test_memory_packet_and_request_sizes_are_bounded(self):
        request = broker.normalize_request({"needs": [{"source": "memory", "query": "q" * 4000},
                                                     {"source": "save_memory"}], "goal": "g" * 4000})
        self.assertEqual(len(request["needs"]), 1)
        self.assertEqual(len(request["needs"][0]["query"]), 500)
        packet = self.collect("memory", {"memories": [{"content": "x" * 10000}] * 100, "episodes": []})
        self.assertTrue(packet["sources"][0]["truncated"])
        self.assertLess(len(broker.render_for_model(packet)), 3500)

    def test_timeout_returns_fast_source_and_limits_inflight_work(self):
        release = threading.Event()
        started = threading.Event()

        def dispatch(source, need):
            if source == "memory":
                started.set()
                release.wait(2)
                return {"memories": []}
            return {"items": [{"title": "提出"}]}

        try:
            with patch.object(broker, "_dispatch", side_effect=dispatch), patch.object(config, "CONTEXT_BROKER_TIMEOUT_SECONDS", 0.03):
                start = time.monotonic()
                packet = broker.collect({"needs": [{"source": "memory", "query": "制作"}, {"source": "reminders"}]})
                self.assertLess(time.monotonic() - start, 0.8)
                self.assertTrue(started.is_set())
                self.assertEqual(packet["sources"][0]["error"], "timeout")
                self.assertEqual(packet["sources"][1]["facts"][0]["title"], "提出")
        finally:
            release.set()

    def test_busy_pool_does_not_queue_unbounded_requests(self):
        with patch.object(broker._SLOTS, "acquire", return_value=False), patch.object(broker._POOL, "submit") as submit:
            packet = broker.collect({"needs": [{"source": "work"}]})
        self.assertEqual(packet["sources"][0]["error"], "source_busy")
        submit.assert_not_called()

    def test_two_call_web_read_keeps_current_work_and_does_not_enter_action_loop(self):
        request = {"needs": [{"source": "work"}, {"source": "memory", "query": "制作"}], "goal": "再開する"}
        first = {"tool_calls": [{"function": {"name": "request_context", "arguments": json.dumps(request)}}]}
        responses = {"work": {"date": "2026-09-07", "total_seconds": 60, "tasks": [], "active": None},
                     "memory": {"memories": [{"content": "次は下書き", "created_at": "2026-09-06"}], "episodes": []}}
        with (
            patch.object(capability_router.situation, "build_active_work_context", return_value="現在の作業: 卒研 (paused)"),
            patch.object(capability_router.workspace_context, "build_context_block", return_value=""),
            patch.object(capability_router, "chat_completion", return_value=first) as first_llm,
            patch.object(broker, "_dispatch", side_effect=lambda source, need: responses[source]),
            patch.object(brain_runtime, "chat_completion", return_value={"content": "卒研の下書きから再開しよう。"}) as second_llm,
            patch.object(brain_runtime.agent_runtime, "_execute_loop") as actions,
        ):
            result = brain_runtime.run("どこから再開しよう？", [])
        first_llm.assert_called_once()
        second_llm.assert_called_once()
        actions.assert_not_called()
        content = json.dumps(second_llm.call_args.args[0], ensure_ascii=False)
        self.assertIn("現在の作業: 卒研", content)
        self.assertIn("次は下書き", content)
        self.assertEqual(result["model_route"]["llm_call_count"], 2)

    def test_failed_response_does_not_claim_success_or_persist_failure_as_memory(self):
        packet = {"sources": [{"source": "memory", "error": "timeout", "facts": []}],
                  "partial": True, "errors": ["memory: timeout"]}
        with (
            patch.object(broker, "collect", return_value=packet),
            patch.object(brain_runtime, "chat_completion", side_effect=brain_runtime.LMStudioError("PRIVATE")),
        ):
            result = brain_runtime._run_context_path("教えて", [], {"context_request": {}})
        self.assertFalse(result["persist"])
        self.assertNotIn("取得できた", result["reply"])
        self.assertNotIn("PRIVATE", result["reply"])


if __name__ == "__main__":
    unittest.main()
