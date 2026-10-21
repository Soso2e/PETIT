from __future__ import annotations

import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from backend import agent, agent_runtime, brain_runtime, capability_router, db, dialogue_state, request_context, tools, work_sessions
from tests import test_dialogue_state as state_tests


class ActionReliabilityTests(unittest.TestCase):
    def setUp(self):
        state_tests.DialogueStateTests.setUp(self)
        blocker = patch.object(agent, "chat_completion", side_effect=AssertionError("Unexpected LLM call"))
        blocker.start()
        self.addCleanup(blocker.stop)
    create = state_tests.DialogueStateTests.create

    def turn(self, text, session="a"):
        with request_context.bind(request_id=text, session_id=session):
            return agent.run(text)

    def test_original_session_conversation(self):
        task = self.create("富美子動画制作", session="fixture")
        with patch.object(agent, "chat_completion", return_value={"content": "まず何をするところから決めよう"}) as llm:
            first = self.turn("セッション開始、富美子動画制作")
            self.assertEqual([t["name"] for t in first["used_tools"]], ["start_work_session"])
            active = work_sessions.active_session()
            self.assertEqual(active["task_id"], str(task["id"]))
            self.turn("セッション開始")
            self.turn("いまカットやってる途中かな〜")
            status = self.turn("セッション開始してくれた？")
            self.assertIn("富美子動画制作", status["reply"])
            self.assertIn("作業中", status["reply"])
            self.turn("開始して")
            self.assertEqual(work_sessions.active_session()["session_id"], active["session_id"])
            self.assertEqual(llm.call_count, 1)  # only the ordinary progress remark

    def test_context_request_cannot_hide_explicit_actions_across_capabilities(self):
        response = {"tool_calls": [{"function": {"name": "request_context", "arguments": json.dumps({"needs": [{"source": "tasks"}], "goal": "調査"})}}]}
        for text, capability in (("セッション開始、富美子動画制作", "work_sessions"),
                                 ("タスク一覧を見て期限を更新して", "lists_and_tasks"),
                                 ("予定を調べて明日の予定を追加して", "calendar")):
            with self.subTest(text=text), patch.object(capability_router, "chat_completion", return_value=response):
                route = capability_router.choose(text)
                self.assertEqual(route["type"], "agent")
                self.assertIn(capability, route["capabilities"])

    def test_context_handoff_reuses_packet_only_for_action(self):
        route = {"type": "context", "capabilities": ["calendar"], "continue_action": True,
                 "context_request": {"needs": [{"source": "calendar", "scope": "tomorrow"}]}}
        packet = {"sources": [{"source": "calendar", "facts": [{"title": "会議"}]}], "partial": False}
        with patch.object(brain_runtime.context_broker, "collect", return_value=packet), \
             patch.object(brain_runtime, "chat_completion") as answer, \
             patch.object(agent_runtime, "_execute_loop", return_value={"reply": "確認待ち"}) as execute:
            brain_runtime._run_context_path("会議の後に予定を追加して", [], route)
        answer.assert_not_called()
        execute.assert_called_once()
        self.assertIn("会議", str(execute.call_args.kwargs["messages"]))

    def test_agent_cannot_report_unexecuted_start(self):
        with patch.object(agent_runtime, "chat_completion", return_value={"content": "セッションを開始したよ。"}):
            result = agent_runtime._execute_loop(original_request="作業開始して", messages=[],
                capabilities=["work_sessions"], selected_names=["start_work_session"])
        self.assertNotEqual(result["reply"], "セッションを開始したよ。")
        self.assertFalse(result["persist"])

    def test_start_tool_result_is_remembered(self):
        task = self.create("富美子動画制作", session="fixture")
        with request_context.bind(request_id="start", session_id="a"):
            tools.dispatch("start_work_session", {"task_id": str(task["id"])})
        state = dialogue_state.load("a")
        self.assertEqual(state["focus_stack"][-1]["entity_id"], task["id"])
        self.assertEqual(state["last_action"]["tool"], "start_work_session")

    def test_previous_exact_mention_is_reference_not_execution(self):
        task = self.create("富美子動画制作", session="fixture")
        with patch.object(agent, "chat_completion", return_value={"content": "動画の話だね"}):
            self.turn("富美子動画制作")
        self.assertIsNone(work_sessions.active_session())
        self.assertEqual(dialogue_state.load("a")["focus_stack"][-1]["entity_id"], task["id"])
        self.turn("開始して")
        self.assertEqual(work_sessions.active_session()["task_id"], str(task["id"]))

    def test_ambiguous_then_candidate_selection(self):
        self.create("富美子動画制作A", session="fixture")
        selected = self.create("富美子動画制作B", session="fixture")
        result = self.turn("セッション開始、富美子動画制作")
        self.assertIn("どのタスク", result["reply"])
        self.assertIsNone(work_sessions.active_session())
        self.turn("開始して")
        self.assertIsNotNone(dialogue_state.load("a")["pending_dialogue"])
        self.turn(f"ID:{selected['id']}")
        self.assertEqual(work_sessions.active_session()["task_id"], str(selected["id"]))

    def test_missing_focus_then_name_completes_original_operation(self):
        task = self.create("富美子動画制作", session="fixture")
        self.turn("セッション開始")
        pending = dialogue_state.load("a")["pending_dialogue"]
        self.assertEqual(pending["original_request"], "セッション開始")
        self.assertEqual(pending["operation"]["kind"], "start_work_session")
        self.turn("富美子動画制作")
        self.assertEqual(work_sessions.active_session()["task_id"], str(task["id"]))

    def test_failure_keeps_id_and_supplement_never_retries(self):
        task = self.create("富美子動画制作", session="fixture")
        from backend.tools import work_sessions as work_tools
        with patch.object(work_tools.work_sessions, "start_session", side_effect=RuntimeError("一時的な保存エラー")):
            failed = self.turn("セッション開始、富美子動画制作")
        self.assertIn("一時的な保存エラー", failed["reply"])
        pending = dialogue_state.load("a")["pending_dialogue"]
        self.assertEqual(pending["candidates"][0]["entity_id"], task["id"])
        self.assertEqual(pending["operation"]["status"], "failed")
        with patch.object(agent, "chat_completion", return_value={"content": "カットの続きだね"}):
            self.turn("いまカットやってる途中かな〜")
        self.assertIsNone(work_sessions.active_session())
        with db.get_connection() as conn:
            conn.execute("UPDATE tasks_cache SET title='改名後' WHERE id=?", (task["id"],))
        self.turn("開始して")
        self.assertEqual(work_sessions.active_session()["task_id"], str(task["id"]))
        self.assertEqual(work_sessions.active_session()["task"], "改名後")

    def test_terminal_and_hidden_tasks_are_distinguished(self):
        for title, status in (("キャンセル動画", "Chancel"), ("完了動画", "done"), ("低優先動画", "todo")):
            task = self.create(title, session="fixture")
            with db.get_connection() as conn:
                conn.execute("UPDATE tasks_cache SET status=?, priority='Low' WHERE id=?", (status, task["id"]))
            result = self.turn(f"セッション開始、{title}")
            if status != "todo":
                self.assertIn("完了・キャンセル", result["reply"])
                self.assertIsNone(work_sessions.active_session())
            else:
                self.assertEqual(work_sessions.active_session()["task_id"], str(task["id"]))
        absent = self.turn("セッション開始、存在しない動画")
        self.assertIn("未同期", absent["reply"])
        self.assertFalse(absent["used_tools"])

    def test_paused_resume_retains_session_and_history(self):
        self.create("富美子動画制作", session="fixture")
        self.turn("セッション開始、富美子動画制作")
        active = work_sessions.active_session()
        work_sessions.pause_session(active["session_id"])
        result = self.turn("セッション開始")
        self.assertIn("再開", result["reply"])
        self.assertEqual(work_sessions.active_session()["session_id"], active["session_id"])
        with db.get_connection() as conn:
            events = [row[0] for row in conn.execute("SELECT event_type FROM work_session_events WHERE session_id=? ORDER BY rowid", (active["session_id"],))]
        self.assertEqual(events, ["started", "paused", "resumed"])

    def test_concurrent_start_tool_is_idempotent_in_database(self):
        task = self.create("富美子動画制作", session="fixture")
        def start(_):
            raw = tools.dispatch("start_work_session", {"task_id": str(task["id"])})
            self.assertFalse(raw.startswith("[error]"), raw)
            return json.loads(raw)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(start, range(4)))
        self.assertEqual(len({item["session"]["session_id"] for item in results}), 1)
        with db.get_connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM work_sessions").fetchone()[0], 1)

    def test_explicit_topic_switch_and_cancel_do_not_replay(self):
        self.create("富美子動画制作", session="fixture")
        with patch.object(agent, "chat_completion", return_value={"content": "うん"}):
            self.turn("富美子動画制作")
            self.turn("ところで夕飯の話にしよう")
        result = self.turn("開始して")
        self.assertFalse(result["used_tools"])
        self.assertIsNone(work_sessions.active_session())
        self.turn("セッション開始、富美子動画制作")
        active = work_sessions.active_session()
        # Cancellation applies to pending clarification, not an already active session.
        work_sessions.end_session(active["session_id"])
        dialogue_state.set_pending("a", {"kind": "start_work_session", "arguments": {}}, [], "セッション開始")
        self.turn("キャンセル")
        result = self.turn("開始して")
        self.assertFalse(result["used_tools"])

    def test_pending_ttl_and_session_isolation(self):
        task = self.create("富美子動画制作", session="fixture")
        ref = dialogue_state.entity(task, "mentioned")
        dialogue_state.set_pending("a", {"kind": "start_work_session", "arguments": {}}, [ref], "開始して")
        old = (datetime.now(timezone.utc) - timedelta(seconds=601)).isoformat()
        with db.get_connection() as conn:
            row = json.loads(conn.execute("SELECT pending_dialogue FROM conversation_state WHERE session_id='a'").fetchone()[0])
            row["created_at"] = old
            conn.execute("UPDATE conversation_state SET pending_dialogue=? WHERE session_id='a'", (json.dumps(row),))
        self.assertIsNone(dialogue_state.load("a")["pending_dialogue"])
        self.turn("開始して", session="b")
        self.assertIsNone(work_sessions.active_session())

    def test_router_failure_still_exposes_required_action_tool(self):
        from backend.lmstudio_client import LMStudioError
        with patch.object(capability_router, "chat_completion", side_effect=LMStudioError("offline")):
            route = capability_router.choose("作業計測を開始して")
        self.assertIn("start_work_session", capability_router.tool_names_for(route["capabilities"]))

    def test_chitchat_after_action_has_one_call_and_no_tools(self):
        history = [{"role": "user", "content": "作業を開始して"}, {"role": "assistant", "content": "開始したよ"}]
        with patch.object(capability_router, "chat_completion", return_value={"content": "おつかれ"}) as llm:
            route = capability_router.choose("いまカットやってる途中かな〜", history)
        self.assertEqual(route["type"], "reply")
        self.assertEqual(llm.call_count, 1)

    def test_agent_failure_cannot_be_reported_as_success(self):
        calls = [{"tool_calls": [{"function": {"name": "start_work_session", "arguments": '{"task_id":"999"}'}}]}, {"content": "開始したよ"}]
        with patch.object(agent_runtime, "chat_completion", side_effect=calls):
            result = agent_runtime._execute_loop(original_request="作業開始して", messages=[], capabilities=["work_sessions"], selected_names=["start_work_session"])
        self.assertIn("完了していません", result["reply"])
        self.assertNotIn("開始したよ", result["reply"])

    def test_http_original_conversation_uses_saved_state(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from backend import chat as chat_api
        task = self.create("富美子動画制作", session="fixture")
        app = FastAPI()
        app.include_router(chat_api.router)
        client = TestClient(app)
        history = []
        with patch.object(chat_api._artifact_executor, "submit"), \
             patch.object(agent, "chat_completion", return_value={"content": "カットの続きだね"}) as llm:
            for text in ("セッション開始、富美子動画制作", "セッション開始", "いまカットやってる途中かな〜", "セッション開始してくれた？", "開始して"):
                response = client.post("/api/chat", json={"message": text, "session_id": "reliability-http", "history": history})
                self.assertEqual(response.status_code, 200)
                result = response.json()
                self.assertFalse(result.get("error"), result)
                self.assertEqual(result["model_route"]["observability"]["llm_calls"], 0)
                history += [{"role": "user", "content": text}, {"role": "assistant", "content": result["reply"]}]
            self.assertEqual(llm.call_count, 1)
        self.assertEqual(work_sessions.active_session()["task_id"], str(task["id"]))
        with db.get_connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM work_sessions").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM conversations WHERE session_id='reliability-http'").fetchone()[0], 5)

    def test_approved_write_receipt_is_not_lost_on_resume(self):
        state = {"original_request": "予定を追加して", "capabilities": ["calendar"], "messages": [], "action_required": True}
        with patch.object(agent_runtime, "chat_completion", return_value={"content": "予定を追加したよ"}) as llm:
            reply = agent_runtime.resume_after_write(state, "add_schedule", {}, '{"added":true}')
        self.assertEqual(reply, "予定を追加したよ")
        self.assertEqual(llm.call_count, 1)
        with patch.object(agent_runtime, "chat_completion", return_value={"content": "予定を追加したよ"}):
            reply = agent_runtime.resume_after_write(state, "add_schedule", {}, '{"added":false,"error":"カレンダー保存失敗"}')
        self.assertIn("カレンダー保存失敗", reply)
        self.assertNotIn("追加したよ", reply)

    def test_no_false_success_from_inconsistent_tool_result(self):
        task = self.create("富美子動画制作", session="fixture")
        with patch.object(tools, "dispatch", return_value=json.dumps({"started": True, "session": {"session_id": "missing", "task_id": str(task["id"])}})):
            result = self.turn("セッション開始、富美子動画制作")
        self.assertIn("開始を確認できません", result["reply"])
        self.assertEqual(dialogue_state.load("a")["last_action"]["status"], "failed")

    def test_read_only_context_does_not_enter_agent(self):
        route = {"context_request": {"needs": [{"source": "tasks"}]}}
        with patch.object(brain_runtime.context_broker, "collect", return_value={"sources": [], "partial": False}), \
             patch.object(brain_runtime, "chat_completion", return_value={"content": "一覧だよ"}) as answer, \
             patch.object(agent_runtime, "_execute_loop") as execute:
            brain_runtime._run_context_path("タスクを見せて", [], route)
        answer.assert_called_once()
        execute.assert_not_called()

    def test_external_id_is_an_explicit_stable_target(self):
        task = self.create("富美子動画制作", session="fixture")
        with db.get_connection() as conn:
            conn.execute("UPDATE tasks_cache SET external_id='notion-page-video' WHERE id=?", (task["id"],))
        self.turn("セッション開始、ID:notion-page-video")
        self.assertEqual(work_sessions.active_session()["task_id"], str(task["id"]))

    def test_deleted_pending_target_never_switches_to_same_title(self):
        task = self.create("富美子動画制作", session="fixture")
        ref = dialogue_state.entity(task, "mentioned")
        dialogue_state.set_pending("a", {"kind": "start_work_session", "arguments": {}}, [ref], "セッション開始")
        with db.get_connection() as conn:
            conn.execute("DELETE FROM tasks_cache WHERE id=?", (task["id"],))
        self.create("富美子動画制作", session="fixture")
        result = self.turn("開始して")
        self.assertFalse(result["used_tools"])
        self.assertIsNone(work_sessions.active_session())

    def test_semantic_action_flag_enforces_evidence_without_keyword(self):
        with patch.object(agent_runtime, "chat_completion", return_value={"content": "全部やったよ"}):
            result = agent_runtime._execute_loop(original_request="いつものように頼む", messages=[],
                capabilities=["work_sessions"], selected_names=["start_work_session"], action_required=True)
        self.assertFalse(result["persist"])
        self.assertNotIn("全部やったよ", result["reply"])

    def test_explicit_project_and_unbound_resume_keep_project_routing(self):
        from backend import dialogue_resolution
        with request_context.bind(request_id="resume", session_id="a"):
            self.assertIsNone(dialogue_resolution.try_handle("再開して"))
            self.create("PETIT", session="a")
            self.assertIsNone(dialogue_resolution.try_handle("PETITプロジェクトの作業を再開して"))


if __name__ == "__main__":
    unittest.main()
