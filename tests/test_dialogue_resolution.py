from __future__ import annotations

import json
import unittest
from datetime import timedelta
from unittest.mock import patch

from backend import agent, brain_runtime, db, dialogue_resolution, dialogue_state, pending_actions, project_router, request_context, time_context, tools
from backend.chat_models import ActionDecision
from tests import test_dialogue_state as _state_tests


class DialogueResolutionTests(unittest.TestCase):
    setUp = _state_tests.DialogueStateTests.setUp
    create = _state_tests.DialogueStateTests.create
    def turn(self, message, session="a"):
        with request_context.bind(request_id=message, session_id=session), patch.object(brain_runtime, "run", side_effect=AssertionError("LLM must not run")):
            return agent.run(message)

    def pending(self, tasks, kind="create_child_task", **args):
        refs = [dialogue_state.entity(task, "mentioned") for task in tasks]
        dialogue_state.set_pending("a", {"kind": kind, "title": "WEVORA", **args}, refs, "その子にWEVORA追加")

    def test_case1_child_of_last_created_without_project_or_llm(self):
        self.create("dotsテスト", turn="old")
        with patch.object(project_router, "try_handle_project_turn", side_effect=AssertionError("project must not run")):
            self.turn("ゲーム開発タスク追加")
            result = self.turn("その子にWEVORA追加")
        self.assertIn("ゲーム開発", result["reply"])
        self.assertEqual([item["name"] for item in result["used_tools"]], ["create_task", "set_task_parent"])
        with db.get_connection() as conn:
            child = dict(conn.execute("SELECT * FROM tasks_cache WHERE title='WEVORA'").fetchone())
            parent = dict(conn.execute("SELECT * FROM tasks_cache WHERE title='ゲーム開発'").fetchone())
        self.assertEqual(child["parent_task_id"], parent["id"])
        self.assertEqual(result["model_route"]["dialogue_resolution_source"], "last_tool_result")

    def test_cases2_3_4_pending_answers_owned_by_tasks(self):
        a, b = self.create("dotsテスト", turn="1"), self.create("ゲーム開発", turn="2")
        for answer in ("ゲーム開発", "後者", "2番", "やっぱりゲーム開発", str(b["id"]), f"ID:{b['id']}"):
            with self.subTest(answer=answer):
                self.pending([a, b])
                with patch.object(project_router, "try_handle_project_turn", side_effect=AssertionError("project must not run")):
                    result = self.turn(answer)
                self.assertIn("ゲーム開発", result["reply"])
                self.assertIsNone(dialogue_state.load("a")["pending_dialogue"])
                with db.get_connection() as conn:
                    row = conn.execute("SELECT parent_task_id FROM tasks_cache WHERE title='WEVORA' ORDER BY id DESC LIMIT 1").fetchone()
                self.assertEqual(row["parent_task_id"], b["id"])

    def test_case5_due_date_uses_stable_id(self):
        task = self.create("PETIT")
        # A similarly named task from a different session must never replace it.
        other = self.create("PETIT2", session="b")
        result = self.turn("その期限明日にして")
        self.assertEqual(result["used_tools"][0]["arguments"], {"task_id": task["id"], "due_date": (time_context.current_datetime().date() + timedelta(days=1)).isoformat()})
        self.assertIsNone(task_hierarchy_task(other["id"])["due_date"])

    def test_case7_two_creates_in_same_turn_ask_without_writing(self):
        self.create("A", turn="same")
        self.create("B", turn="same")
        result = self.turn("その子にWEVORA追加")
        self.assertIn("どのタスク", result["reply"])
        self.assertFalse(result["used_tools"])
        pending = dialogue_state.load("a")["pending_dialogue"]
        self.assertEqual(pending["missing_slot"], "parent_task")
        result = self.turn("後者")
        self.assertIn("「B」の子", result["reply"])

    def test_case8_no_cross_session_pending_or_focus(self):
        self.create("A")
        self.turn("その子にWEVORA追加", session="b")
        self.assertIsNotNone(dialogue_state.load("b")["pending_dialogue"])
        self.assertIsNone(dialogue_state.load("a")["pending_dialogue"])
        self.assertEqual(len(dialogue_state.load("a")["focus_stack"]), 1)

    def test_reference_variants(self):
        for ref in ("その", "それ", "これ", "こいつ", "さっきの"):
            self.create("A", turn=ref)
            self.assertIn("変更した", self.turn(f"{ref}の期限明日にして")["reply"])
        for child in ("子", "子供", "下"):
            self.create("親", turn=child)
            self.assertIn("の子", self.turn(f"その{child}に子{child}追加")["reply"])

    def test_pending_ambiguous_pronoun_never_guesses_and_cancel(self):
        a, b = self.create("A", turn="1"), self.create("B", turn="2")
        self.pending([a, b])
        self.assertFalse(self.turn("それ")["used_tools"])
        self.assertIsNotNone(dialogue_state.load("a")["pending_dialogue"])
        self.assertIn("キャンセル", self.turn("キャンセル")["reply"])
        self.assertIsNone(dialogue_state.load("a")["pending_dialogue"])

    def test_single_candidate_pronoun_and_former(self):
        a, b = self.create("A", turn="1"), self.create("B", turn="2")
        for candidates, answer, name in (([a], "それ", "A"), ([a,b], "前者", "A"), ([a,b], "1番", "A")):
            self.pending(candidates)
            self.assertIn(f"「{name}」の子", self.turn(answer)["reply"])

    def test_stale_candidate_not_replaced_by_same_title(self):
        a = self.create("A")
        self.pending([a])
        with db.get_connection() as conn:
            conn.execute("DELETE FROM tasks_cache WHERE id=?", (a["id"],))
        self.create("A", session="b")
        result = self.turn("A")
        self.assertFalse(result["used_tools"])
        self.assertEqual(result["model_route"]["dialogue_resolution_source"], "stale_candidate")

    def test_missing_focus_exact_name_answer_can_continue(self):
        a = self.create("ゲーム開発", session="b")
        self.turn("その子にWEVORA追加")
        self.assertIn("ゲーム開発", self.turn("ゲーム開発")["reply"])

    def test_previous_focus(self):
        a, b = self.create("A", turn="1"), self.create("B", turn="2")
        result = self.turn("前の期限明日にして")
        self.assertEqual(result["used_tools"][0]["arguments"]["task_id"], a["id"])

    def test_previous_of_ambiguous_turn_requires_selection(self):
        self.create("A", turn="same")
        self.create("B", turn="same")
        self.assertFalse(self.turn("前の期限明日にして")["used_tools"])

    def test_policy_still_blocks_confirmation_writes(self):
        self.create("A")
        with patch.object(tools, "risk_for", return_value="confirm_write"), patch.object(tools, "dispatch") as dispatch:
            self.assertIn("確認が必要", self.turn("その期限明日にして")["reply"])
        dispatch.assert_not_called()

    def test_invalid_parent_prevents_orphan_creation(self):
        parent, child = self.create("親", turn="1"), self.create("子", turn="2")
        with request_context.bind(request_id="link", session_id="a"):
            tools.dispatch("set_task_parent", {"task_id": child["id"], "parent_task_id": parent["id"]})
        result = self.turn("その子に孫追加")
        self.assertFalse(result["used_tools"])
        self.assertIn("Life直下", result["reply"])

    def test_unsupported_task_anaphora_never_goes_to_llm(self):
        self.create("A")
        self.assertEqual(self.turn("その期限来週月曜にして")["model_route"]["dialogue_resolution_source"], "unsupported_task_anaphora")

    def test_confirmation_api_preserves_original_session_for_tool_hook(self):
        actions = pending_actions.register([{"name": "create_task", "arguments": {"title": "承認タスク"}}], session_id="a")
        result = pending_actions.decide_action(actions[0].approval_id, ActionDecision(approved=True))
        self.assertFalse(result.error)
        self.assertEqual(dialogue_state.load("a")["focus_stack"][-1]["title"], "承認タスク")
        self.assertFalse(dialogue_state.load("b"))

    def test_case9_restored_pending_executes_and_expired_pending_does_not_own_answer(self):
        import importlib
        from datetime import datetime, timezone
        a, b = self.create("A", turn="1"), self.create("ゲーム開発", turn="2")
        self.pending([a, b])
        importlib.reload(dialogue_state)
        self.assertIn("ゲーム開発", self.turn("後者")["reply"])
        self.pending([a, b])
        pending = dialogue_state.load("a")["pending_dialogue"]
        pending["created_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with db.get_connection() as conn:
            conn.execute("UPDATE conversation_state SET pending_dialogue=? WHERE session_id='a'", (json.dumps(pending),))
        with request_context.bind(request_id="expired", session_id="a"), patch.object(brain_runtime, "run", return_value={"reply": "normal"}) as brain:
            self.assertEqual(agent.run("ゲーム開発")["reply"], "normal")
        brain.assert_called_once()

    def test_new_topic_releases_pending(self):
        self.pending([self.create("A")])
        with request_context.bind(request_id="new", session_id="a"), patch.object(brain_runtime, "run", return_value={"reply": "weather"}):
            self.assertEqual(agent.run("ところで今日の天気教えて")["reply"], "weather")
        self.assertIsNone(dialogue_state.load("a")["pending_dialogue"])

    def test_duplicate_names_require_id_or_ordinal(self):
        a, b = self.create("A", turn="1"), self.create("A", turn="2")
        self.pending([a, b])
        self.assertFalse(self.turn("A")["used_tools"])
        self.assertIn("の子", self.turn("2番")["reply"])

    def test_corrupt_pending_does_not_break_regular_chat(self):
        self.create("A")
        with db.get_connection() as conn:
            conn.execute("UPDATE conversation_state SET pending_dialogue=? WHERE session_id='a'", (json.dumps({"created_at": db.now_iso(), "owner": "tasks"}),))
        with request_context.bind(request_id="normal", session_id="a"), patch.object(brain_runtime, "run", return_value={"reply": "hello"}):
            self.assertEqual(agent.run("こんにちは")["reply"], "hello")

    def test_named_completion_ambiguity_saves_pending(self):
        a, b = self.create("PETIT A", turn="1"), self.create("PETIT B", turn="2")
        self.turn("PETIT完了")
        self.assertEqual(dialogue_state.load("a")["pending_dialogue"]["kind"], "complete_task")
        result = self.turn("後者")
        self.assertEqual(result["used_tools"][0]["arguments"]["task_id"], b["id"])


def task_hierarchy_task(task_id):
    from backend import task_hierarchy
    return task_hierarchy._find_task(task_id)
