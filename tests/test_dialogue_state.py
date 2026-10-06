from __future__ import annotations

import importlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from backend import config, conversation_state, db, dialogue_state, request_context, tools


class DialogueStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_patch = patch.object(config, "DB_PATH", Path(self.temp.name) / "app.db")
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        db.init_db()
        self.notion = patch.object(config, "notion_configured", return_value=False)
        self.notion.start()
        self.addCleanup(self.notion.stop)

    def create(self, title="PETIT", session="a", turn="turn"):
        with request_context.bind(request_id=turn, session_id=session):
            return json.loads(tools.dispatch("create_task", {"title": title}))["task"]

    def test_successful_writes_promote_stable_ids_and_roles(self):
        task = self.create()
        for name, args, role in (("update_task", {"title": "PETIT2"}, "last_updated"),
                                 ("complete_task", {}, "last_completed")):
            with request_context.bind(request_id=name, session_id="a"):
                tools.dispatch(name, {"task_id": task["id"], **args})
            state = dialogue_state.load("a")
            ref = state["focus_stack"][-1]
            self.assertEqual(ref["entity_id"], task["id"])
            self.assertEqual(ref["role"], role)
            self.assertEqual(ref["source"], "local")
            self.assertEqual(ref["entity_type"], "task")
            self.assertTrue(ref["updated_at"])
            self.assertEqual(state["last_action"]["tool"], name)

    def test_failed_tools_and_list_reads_do_not_replace_focus(self):
        task = self.create()
        for name, args in (("create_task", {"title": ""}), ("update_task", {"task_id": 999, "title": "x"}),
                           ("get_tasks", {"status": "all", "priority": "all"})):
            with request_context.bind(request_id="next", session_id="a"):
                tools.dispatch(name, args)
        self.assertEqual(dialogue_state.load("a")["focus_stack"][-1]["entity_id"], task["id"])
        for result in ({"created": False, "task": task}, {"created": True, "error": "bad", "task": task},
                       {"created": True, "partial_update": True, "task": task},
                       "[error] bad", "not json", {"created": True, "task": {"id": True, "title": "bad"}}):
            dialogue_state.observe_tool_result(session_id="b", tool="create_task", arguments={}, result=result)
        self.assertFalse(dialogue_state.load("b"))

    def test_session_isolation_and_no_session(self):
        self.create(session="a")
        self.assertFalse(dialogue_state.load("b"))
        self.create(session=None)
        self.assertEqual(len(dialogue_state.load("a")["focus_stack"]), 1)
        self.assertFalse(dialogue_state.load(None))

    def test_restart_restores_focus_and_pending_and_expires_pending(self):
        task = self.create()
        candidate = dialogue_state.entity(task, "mentioned")
        dialogue_state.set_pending("a", {"kind": "create_child_task", "title": "WEVORA"}, [candidate], "その子にWEVORA追加")
        importlib.reload(dialogue_state)
        state = dialogue_state.load("a")
        self.assertEqual(state["focus_stack"][-1]["entity_id"], task["id"])
        self.assertEqual(state["pending_dialogue"]["owner"], "tasks")
        pending = state["pending_dialogue"]
        pending["created_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with db.get_connection() as conn:
            conn.execute("UPDATE conversation_state SET pending_dialogue=? WHERE session_id='a'", (json.dumps(pending),))
        self.assertIsNone(dialogue_state.load("a")["pending_dialogue"])

    def test_pending_consumed_once(self):
        dialogue_state.set_pending("a", {"kind": "select_task"}, [], "それ")
        key = dialogue_state.load("a")["pending_dialogue"]["id"]
        self.assertFalse(dialogue_state.take_pending("a", "wrong"))
        self.assertTrue(dialogue_state.take_pending("a", key))
        self.assertFalse(dialogue_state.take_pending("a", key))

    def test_compact_turn_update_preserves_dialogue_fields_and_bounds_stack(self):
        for index in range(12):
            self.create(str(index), turn=str(index))
        before = dialogue_state.load("a")
        conversation_state.update_after_turn("a", user_text="別の話", assistant_text="了解")
        after = dialogue_state.load("a")
        self.assertEqual(len(after["focus_stack"]), dialogue_state.MAX_FOCUS)
        self.assertEqual(before["focus_stack"], after["focus_stack"])
        self.assertEqual(before["last_action"], after["last_action"])

    def test_existing_schema_migration_preserves_summary(self):
        with db.get_connection() as conn:
            conn.executescript(conversation_state._SCHEMA)
            conn.execute("INSERT INTO conversation_state (session_id, current_topic, updated_at) VALUES ('old', 'topic', ?)", (db.now_iso(),))
        conversation_state.ensure_schema()
        self.assertEqual(conversation_state.load("old")["current_topic"], "topic")
        self.assertEqual(conversation_state.load("old")["focus_stack"], [])

    def test_state_failure_does_not_fail_tool(self):
        with patch.object(dialogue_state, "observe_tool_result", side_effect=RuntimeError("broken")):
            self.assertTrue(self.create()["id"])
        with patch.object(conversation_state, "load", side_effect=RuntimeError("broken")):
            self.assertEqual(dialogue_state.load("a"), {})

    def test_parent_is_related_child_is_primary(self):
        parent, child = self.create("親", turn="1"), self.create("子", turn="2")
        with request_context.bind(request_id="3", session_id="a"):
            result = json.loads(tools.dispatch("set_task_parent", {"task_id": child["id"], "parent_task_id": parent["id"]}))
        self.assertTrue(result["updated"])
        stack = dialogue_state.load("a")["focus_stack"]
        self.assertEqual([item["role"] for item in stack], ["parent", "child"])


if __name__ == "__main__":
    unittest.main()
