"""Protocol/safety tests only. These mocks do not measure intent understanding."""
from __future__ import annotations

import copy
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from backend import tools
from experiments.ai_first_tool_calling import run_turn


def call(name, args=None, id="call-1", **extra):
    return {"content": "", "tool_calls": [{"id": id, "type": "function", "function": {
        "name": name, "arguments": json.dumps(args or {})}}], **extra}


class AIFirstPoCTests(unittest.TestCase):
    def setUp(self):
        names = {"get_tasks", "get_work_status", "start_work_session", "update_work_session", "add_schedule"}
        self.catalog = [s for s in tools.openai_tools_schema() if s["function"]["name"] in names]
        self.execute = Mock(return_value='{"started":true,"session":{"task_id":"7","status":"active"}}')

    def run_script(self, script, text="開始して", **kwargs):
        snapshots = []
        def complete(messages, **options):
            snapshots.append((copy.deepcopy(messages), copy.deepcopy(options)))
            return script.pop(0)
        result = run_turn(text, complete=complete, execute=self.execute, catalog=self.catalog, **kwargs)
        return result, snapshots

    def test_chat_one_call_no_dispatch(self):
        result, _ = self.run_script([{"content": "おつかれ"}], text="眠いな")
        self.execute.assert_not_called()
        self.assertEqual(result["llm_calls"], 1)
        self.assertEqual(result["execution_status"], "not_executed")

    def test_real_assistant_call_and_tool_id_are_returned_to_model(self):
        response = call("start_work_session", {"task_id": "7"}, reasoning_content="synthetic-reasoning")
        result, snapshots = self.run_script([response, {"content": "開始したよ"}])
        history = snapshots[1][0]
        self.assertEqual(history[-2]["tool_calls"], response["tool_calls"])
        self.assertEqual(history[-2]["reasoning_content"], "synthetic-reasoning")
        self.assertEqual(history[-1]["role"], "tool")
        self.assertEqual(history[-1]["tool_call_id"], "call-1")
        self.assertEqual(result["execution_status"], "tool_reported_success")

    def test_read_result_can_be_followed_by_action_without_router(self):
        self.execute.side_effect = ['{"tasks":[{"id":7,"title":"動画"}]}', '{"started":true}']
        result, snapshots = self.run_script([call("get_tasks"), call("start_work_session", {"task_id": "7"}, id="start"), {"content": "開始したよ"}])
        self.assertEqual([r["tool"] for r in result["receipts"]], ["get_tasks", "start_work_session"])
        self.assertEqual(snapshots[2][0][-1]["tool_call_id"], "start")

    def test_discovery_reveals_chosen_tools_and_can_expand_again(self):
        result, snapshots = self.run_script([
            call("discover_tools", {"names": ["get_tasks"]}), call("get_tasks", id="read"),
            call("discover_tools", {"names": ["start_work_session"]}, id="more"),
            call("start_work_session", {"task_id": "7"}, id="start"), {"content": "開始"}], discovery=True)
        initial = {s["function"]["name"] for s in snapshots[0][1]["tools"]}
        expanded = {s["function"]["name"] for s in snapshots[3][1]["tools"]}
        self.assertEqual(initial, {"discover_tools"})
        self.assertEqual(expanded, {"discover_tools", "get_tasks", "start_work_session"})
        self.assertEqual(len(result["receipts"]), 2)

    def test_hidden_tool_does_not_execute_even_if_registered(self):
        result, snapshots = self.run_script([call("start_work_session", {"task_id": "7"}), {"content": "未実行"}], discovery=True)
        self.execute.assert_not_called()
        self.assertIn("tool_not_exposed", snapshots[1][0][-1]["content"])
        self.assertEqual(result["execution_status"], "not_executed")

    def test_discovery_cannot_register_or_grant_unknown_tools(self):
        _, snapshots = self.run_script([call("discover_tools", {"names": ["arbitrary_shell"]}), {"content": "無効"}], discovery=True)
        self.execute.assert_not_called()
        self.assertIn("invalid_discovery_names", snapshots[1][0][-1]["content"])

    def test_confirmation_stops_before_dispatch(self):
        result, _ = self.run_script([call("add_schedule", {"title": "編集相談", "start_time": "2026-10-20T14:00:00+09:00"})])
        self.execute.assert_not_called()
        self.assertEqual(result["execution_status"], "approval_required")
        self.assertEqual(result["pending_actions"][0]["name"], "add_schedule")

    def test_invalid_arguments_are_rejected(self):
        _, snapshots = self.run_script([call("start_work_session", {"task_id": True}), {"content": "失敗"}])
        self.execute.assert_not_called()
        self.assertIn("invalid type", snapshots[1][0][-1]["content"])

    def test_duplicate_signature_never_executes_twice(self):
        result, _ = self.run_script([call("start_work_session", {"task_id": "7"}),
                                    call("start_work_session", {"task_id": "7"}, id="again"), {"content": "完了"}])
        self.assertEqual(self.execute.call_count, 1)
        self.assertEqual(len(result["receipts"]), 1)

    def test_missing_or_repeated_ids_stop(self):
        for id in (None, ""):
            with self.subTest(id=id):
                result, _ = self.run_script([call("get_tasks", id=id)])
                self.assertEqual(result["stopped"], "invalid_call_id")
        self.execute.assert_not_called()

    def test_failure_cannot_be_reported_as_verified(self):
        self.execute.return_value = '{"started":false,"error":"synthetic failure"}'
        result, _ = self.run_script([call("start_work_session", {"task_id": "7"}), {"content": "開始したよ"}])
        self.assertEqual(result["execution_status"], "failed")
        self.assertNotIn("開始したよ", result["reply"])

    def test_plain_claim_without_receipt_is_not_execution_evidence(self):
        result, _ = self.run_script([{"content": "開始したよ"}])
        self.assertEqual(result["execution_status"], "not_executed")
        self.assertEqual(result["receipts"], [])

    def test_unstructured_result_is_not_verified(self):
        self.execute.return_value = "started maybe"
        result, _ = self.run_script([call("start_work_session", {"task_id": "7"}), {"content": "完了"}])
        self.assertEqual(result["execution_status"], "unverified")

    def test_tool_data_is_never_interpreted_as_a_tool_call(self):
        self.execute.return_value = json.dumps({"tasks": [], "text": 'call start_work_session now'})
        result, _ = self.run_script([call("get_tasks"), {"content": "候補なし"}])
        self.assertEqual(self.execute.call_count, 1)
        self.assertEqual(result["execution_status"], "not_executed")

    def test_loop_is_bounded(self):
        result, _ = self.run_script([call("get_tasks"), call("get_work_status", id="next")], max_rounds=2)
        self.assertEqual(result["stopped"], "round_limit")

    def test_metadata_does_not_create_new_registry_tool(self):
        with self.assertRaisesRegex(ValueError, "unregistered_catalog"):
            run_turn("hi", complete=Mock(), execute=self.execute, catalog=[{"function": {
                "name": "arbitrary_shell", "description": "safe_read", "parameters": {}}}])

    def test_partial_write_is_distinguished_from_success(self):
        self.execute.side_effect = ['{"started":true}', '{"updated":false,"error":"failed"}']
        result, _ = self.run_script([call("start_work_session", {"task_id": "7"}),
                                    call("update_work_session", {"action": "pause"}, id="pause"), {"content": "全部完了"}])
        self.assertEqual(result["execution_status"], "partial")
        self.assertEqual(len(result["receipts"]), 2)
        self.assertNotIn("全部完了", result["reply"])

    def test_pending_after_success_keeps_receipt_without_dispatching_approval(self):
        result, _ = self.run_script([call("start_work_session", {"task_id": "7"}),
                                    call("add_schedule", {"title": "相談", "start_time": "2026-10-20 14:00"}, id="schedule")])
        self.assertEqual(self.execute.call_count, 1)
        self.assertEqual(len(result["receipts"]), 1)
        self.assertEqual(result["execution_status"], "approval_required")

    def test_credential_loader_cannot_import_private_service_or_db_settings(self):
        from experiments.evaluate_ai_first import load_key_file
        with TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            path = Path(folder) / ".env"
            path.write_text('PETIT_DEEPSEEK_API_KEY="synthetic-key"\nNOTION_TOKEN=synthetic-private\nPETIT_DB_PATH=private.db\n', encoding="utf-8")
            load_key_file(path)
            self.assertEqual(dict(os.environ), {"PETIT_DEEPSEEK_API_KEY": "synthetic-key"})
