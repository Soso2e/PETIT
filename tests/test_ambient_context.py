from __future__ import annotations

import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from backend import (ambient, brain, config, conversation_api as api, conversation_store as store, db,
                     external_brain, request_context, time_context, tools, work_sessions)

HEADER = "Coreが取得済みの現在状況"


class AmbientContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for target, value in (("DB_PATH", Path(self.temp.name) / "app.db"), ("notion_configured", lambda: False),
                              ("AMBIENT_CONTEXT", True), ("AMBIENT_MAX_CHARS", 1800)):
            p = patch.object(config, target, value)
            p.start()
            self.addCleanup(p.stop)
        p_env = patch.dict("os.environ", {"PETIT_SETTINGS_DIR": str(Path(self.temp.name) / "settings")})
        p_env.start()
        self.addCleanup(p_env.stop)
        from backend import setup_store as _settings
        _settings._sessions.clear()
        for target in ("backend.chroma_client.sync_structured_data", "backend.chroma_client.add",
                       "backend.chroma_client.delete_ids", "backend.chat._artifact_executor.submit"):
            p = patch(target)
            p.start()
            self.addCleanup(p.stop)
        db.init_db()
        store.ensure_schema()
        tools.register_builtin_tools()

    def turn(self, message="相談", request_id="r", thread="a", is_admin=True, reply="了解。"):
        with patch.object(brain.lmstudio_client, "chat_completion",
                          side_effect=[{"role": "assistant", "content": reply}]) as model:
            result = api.submit(thread, request_id, message, is_admin=is_admin)
        return result, model.call_args.args[0]

    def owner(self, thread="a"):
        return request_context.bind(request_id="x", session_id=thread, is_admin=True)

    def seed(self):
        today = time_context.current_datetime()
        json.loads(tools.dispatch("create_task", {"title": "卒研の実験計画", "priority": "High"}))
        tools.dispatch("add_schedule", {"title": "ゼミ", "start_time": today.date().isoformat() + " 15:00",
                                        "end_time": today.date().isoformat() + " 16:30", "location": "3号館"})
        tools.dispatch("add_schedule", {"title": "歯医者", "start_time":
                                        (today.date() + timedelta(days=1)).isoformat() + " 10:00"})
        tools.dispatch("add_schedule", {"title": "来週の旅行", "start_time":
                                        (today.date() + timedelta(days=6)).isoformat() + " 09:00"})
        work_sessions.start_session("ws-1", "WEVORAの敵AI")

    def blocks(self, messages):
        return [m["content"] for m in messages if m["role"] == "user" and str(m["content"]).startswith(HEADER)]

    def test_nothing_known_adds_no_message(self):
        result, messages = self.turn()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.blocks(messages), [])
        self.assertEqual(messages[-1], {"role": "user", "content": "相談"})

    def test_known_state_is_handed_over_before_the_request(self):
        self.seed()
        result, messages = self.turn("WEVORAの敵AIどうするんだっけ")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(messages[-1]["content"], "WEVORAの敵AIどうするんだっけ")
        self.assertTrue(messages[-2]["content"].startswith(HEADER))
        block = messages[-2]["content"]
        for expected in ("[作業] 計測中: WEVORAの敵AI", "15:00-16:30 ゼミ @3号館", "10:00 歯医者",
                         "卒研の実験計画"):
            with self.subTest(expected=expected):
                self.assertIn(expected, block)
        self.assertNotIn("来週の旅行", block)
        self.assertLessEqual(len(block), config.AMBIENT_MAX_CHARS)

    def test_event_log_keeps_counts_not_content(self):
        self.seed()
        self.turn("WEVORAの敵AIどうするんだっけ")
        with db.get_connection() as connection:
            rows = connection.execute("SELECT payload_json FROM turn_events WHERE type='ambient_context'").fetchall()
        self.assertEqual(len(rows), 1)
        payload = json.loads(rows[0]["payload_json"])
        self.assertEqual(payload["sections"], {"work": 1, "schedule": 2, "tasks": 1})
        self.assertNotIn("WEVORA", rows[0]["payload_json"])
        self.assertNotIn("ゼミ", rows[0]["payload_json"])

    def test_block_is_not_replayed_from_history(self):
        self.seed()
        self.turn("WEVORAの進み具合は", request_id="r1")
        _result, messages = self.turn("ありがとう", request_id="r2")
        self.assertEqual(len(self.blocks(messages)), 1)

    def test_guest_gets_no_owner_data(self):
        self.seed()
        _result, messages = self.turn("WEVORAの敵AIどうするんだっけ", is_admin=False)
        self.assertEqual(self.blocks(messages), [])
        self.assertNotIn("ゼミ", json.dumps(messages, ensure_ascii=False))

    def test_guild_work_thread_and_switch_get_nothing(self):
        self.seed()
        from backend import delegations
        with self.owner():
            self.assertTrue(ambient.build("a")["text"])
            with request_context.guild_mode(guild_id="g1"):
                self.assertEqual(ambient.build("a")["text"], "")
        with self.owner(delegations.WORK_PREFIX + "x"):
            self.assertEqual(ambient.build(delegations.WORK_PREFIX + "x")["text"], "")
        with self.owner(), patch.object(config, "AMBIENT_CONTEXT", False):
            self.assertEqual(ambient.build("a")["text"], "")

    def test_a_failing_section_does_not_remove_the_others(self):
        self.seed()
        with self.owner(), patch.object(work_sessions, "active_session", side_effect=RuntimeError("boom")):
            built = ambient.build("a")
        self.assertNotIn("work", built["sections"])
        self.assertIn("schedule", built["sections"])
        self.assertIn("tasks", built["sections"])

    def test_budget_keeps_whole_sections_in_priority_order(self):
        self.seed()
        with self.owner():
            full = ambient.build("a")
            with patch.object(config, "AMBIENT_MAX_CHARS", full["chars"] - 1):
                small = ambient.build("a")
        self.assertEqual(list(full["sections"]), ["work", "schedule", "tasks"])
        self.assertLess(small["chars"], full["chars"])
        self.assertEqual(list(small["sections"]), ["work", "schedule"])
        for line in small["text"].splitlines()[2:]:
            self.assertIn(line, full["text"])

    def test_due_soon_lists_other_priorities_once(self):
        today = time_context.current_datetime().date()
        tools.dispatch("create_task", {"title": "レポート提出", "priority": "Low",
                                       "due_date": (today + timedelta(days=1)).isoformat()})
        tools.dispatch("create_task", {"title": "来月の準備", "priority": "Low",
                                       "due_date": (today + timedelta(days=30)).isoformat()})
        tools.dispatch("create_task", {"title": "発表資料", "priority": "High",
                                       "due_date": today.isoformat()})
        with self.owner():
            text = ambient.build("a")["text"]
        self.assertEqual(text.count("発表資料"), 1)
        self.assertIn("レポート提出", text)
        self.assertNotIn("来月の準備", text)

    def test_saved_memories_are_not_offered_unasked(self):
        # Most stored rows are state at the time of an episode summary; they stay behind search_memory.
        self.seed()
        db.save_memory_item("WEVORAの同期状態は正常で競合はない", "fact", "auto_episode")
        db.save_memory_item("WEVORAの敵AIはビヘイビアツリーで作る方針", "decision", "explicit")
        _result, messages = self.turn("WEVORAの敵AIどうするんだっけ")
        self.assertNotIn("ビヘイビアツリー", json.dumps(messages, ensure_ascii=False))
        self.assertNotIn("同期状態は正常", json.dumps(messages, ensure_ascii=False))

    def test_cli_brains_receive_the_same_block_but_not_on_approval_resume(self):
        self.seed()
        row, _created = store.accept(store.create_thread("cli")["id"], "cli-r", {
            "message": "WEVORAの敵AIどうするんだっけ", "is_admin": True})
        with self.owner("cli"):
            _instructions, prompt = external_brain.context("cli-r")
            _instructions, resumed = external_brain.context("cli-r", [{"role": "user", "content": "x"}])
        self.assertIn("known_situation", prompt)
        self.assertIn("15:00-16:30 ゼミ", prompt)
        self.assertNotIn("known_situation", resumed)
        with db.get_connection() as connection:
            count = connection.execute("SELECT COUNT(*) FROM turn_events WHERE type='ambient_context'").fetchone()[0]
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
