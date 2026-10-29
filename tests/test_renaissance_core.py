from __future__ import annotations

import importlib
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import brain, config, conversation_api as api, conversation_store as store, db, tools, work_sessions


def call(name, arguments=None, call_id="call-1"):
    return {"id": call_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments or {}, ensure_ascii=False)}}


class RenaissanceCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for target, value in (
            ("DB_PATH", Path(self.temp.name) / "app.db"),
            ("notion_configured", lambda: False),
        ):
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

    def turn(self, responses, message="相談", request_id="r", thread="a", is_admin=True):
        with patch.object(brain.lmstudio_client, "chat_completion", side_effect=responses) as model:
            result = api.submit(thread, request_id, message, is_admin=is_admin)
        return result, model

    def task(self, name="卒研"):
        return json.loads(tools.dispatch("create_task", {"title": name}))["task"]

    def test_one_call_conversation_uses_native_tools_without_router(self):
        result, model = self.turn([{"role": "assistant", "content": "どこから考えようか。"}])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(model.call_count, 1)
        names = {s["function"]["name"] for s in model.call_args.kwargs["tools"]}
        self.assertIn("get_tasks", names)
        self.assertNotIn("route_agent", names)
        self.assertNotIn("request_context", names)
        self.assertNotIn("execute_agent_write", names)

    def test_explicit_shared_thread_preserves_each_utterance_source(self):
        with patch.object(brain.lmstudio_client, "chat_completion", return_value={"content": "返答"}):
            api.submit("shared", "web-r", "Webから", source="web")
            api.submit("shared", "desktop-r", "Desktopから", source="desktop")
            api.submit("discord-thread", "discord-r", "Discordから", source="discord")
        with db.get_connection() as connection:
            self.assertEqual([r["source"] for r in connection.execute("SELECT source FROM conversations ORDER BY id")],
                             ["web", "desktop", "discord"])

    def test_actual_work_session_and_receipt_survive_response_replay(self):
        task = self.task()
        result, model = self.turn([
            {"tool_calls": [call("start_work_session", {"task_id": str(task["id"])})]},
            {"content": "卒研の作業を開始したよ。"},
        ], message="取り掛かろう", request_id="start")
        self.assertEqual(work_sessions.active_session()["task_id"], str(task["id"]))
        self.assertEqual(result["effects"][0]["status"], "applied")
        saved = work_sessions.active_session()["session_id"]
        importlib.reload(store)
        with patch.object(brain.lmstudio_client, "chat_completion", side_effect=AssertionError("replayed model")):
            replay = api.submit("a", "start", "取り掛かろう")
        self.assertEqual(replay["reply"], result["reply"])
        self.assertEqual(work_sessions.active_session()["session_id"], saved)
        with db.get_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM conversations").fetchone()[0], 1)
        messages = model.call_args.args[0]
        self.assertTrue(any(m.get("tool_call_id") == "call-1" for m in messages))

    def test_local_effect_and_receipt_roll_back_together(self):
        task = self.task()
        store.create_thread("a")
        store.accept("a", "r", {"message": "始める"})
        with patch.object(store, "end_effect", side_effect=RuntimeError("disk failure")):
            with self.assertRaises(RuntimeError):
                brain.execute("r", call("start_work_session", {"task_id": str(task["id"])}),
                              {"task_id": str(task["id"])})
        self.assertIsNone(work_sessions.active_session())
        self.assertIsNone(store.receipt("r", "call-1"))

    def test_handler_failure_does_not_commit_its_partial_local_write(self):
        from backend.tools import registry
        store.create_thread("a")
        store.accept("a", "r", {"message": "記録"})
        def broken(**kwargs):
            db.save_memory_item("保存途中の値", "note", "explicit")
            raise ValueError("failed after domain write")
        with patch.object(registry._REGISTRY["save_memory"], "handler", side_effect=broken):
            raw = brain.execute("r", call("save_memory", {"content": "x"}), {"content": "x"})
        self.assertTrue(brain.failed(raw))
        with db.get_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM memory").fetchone()[0], 0)
        self.assertEqual(store.receipt("r", "call-1")["status"], "failed")

    def test_duplicate_write_with_different_call_id_is_not_repeated(self):
        args = {"content": "卒研の発表日は11月2日", "type": "fact"}
        result, _ = self.turn([
            {"tool_calls": [call("save_memory", args, "one"), call("save_memory", args, "two")]},
            {"content": "発表日を記録したよ。"},
        ])
        with db.get_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM memory").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM effect_receipts").fetchone()[0], 1)
        self.assertEqual(result["effects"][0]["status"], "applied")

    def test_same_request_id_conflicts_on_changed_input_or_thread(self):
        self.turn([{"content": "返答"}])
        for thread, message in (("a", "違う入力"), ("b", "相談")):
            with self.assertRaises(HTTPException) as error:
                api.submit(thread, "r", message)
            self.assertEqual(error.exception.status_code, 409)

    def test_concurrent_acceptance_has_one_winner_and_one_thread_slot(self):
        store.create_thread("a")
        with ThreadPoolExecutor(2) as executor:
            results = list(executor.map(lambda _: store.accept("a", "r", {"message": "x"})[1], range(2)))
        self.assertEqual(sum(results), 1)
        with self.assertRaises(HTTPException) as error:
            store.accept("a", "other", {"message": "y"})
        self.assertEqual(error.exception.status_code, 429)

    def test_other_threads_and_legacy_null_sessions_are_not_prompt_history(self):
        db.save_conversation("別スレッドの秘密", "秘密の返答", session_id="b")
        db.save_conversation("出典不明の旧履歴", "旧返答")
        db.save_conversation("この会話の相談", "同じ会話", session_id="a")
        _, model = self.turn([{"content": "続きを考えるね"}])
        text = json.dumps(model.call_args.args[0], ensure_ascii=False)
        self.assertIn("この会話の相談", text)
        self.assertNotIn("別スレッドの秘密", text)
        self.assertNotIn("出典不明の旧履歴", text)

    def test_private_thread_blocks_cloud_before_any_model_call(self):
        store.create_thread("a", privacy="local_only")
        with patch.object(brain.lmstudio_client, "endpoint", return_value={"provider": "deepseek"}):
            result, model = self.turn([{"content": "must not send"}])
        self.assertEqual(result["status"], "failed")
        model.assert_not_called()

    def test_provider_boundary_also_protects_non_chat_private_calls(self):
        from backend import request_context, lmstudio_client
        store.create_thread("a", privacy="local_only")
        target = {"provider": "deepseek", "base_url": "https://api.deepseek.com"}
        with request_context.bind(request_id="r", session_id="a"), patch.object(lmstudio_client.httpx, "post") as http:
            with self.assertRaises(lmstudio_client.LMStudioError):
                lmstudio_client.chat_completion([{"role": "user", "content": "private"}], target_override=target)
        http.assert_not_called()

    def test_private_memory_never_becomes_public_on_partial_rollout(self):
        from backend import request_context
        store.create_thread("a", privacy="local_only")
        store.accept("a", "r", {"message": "個人の記憶"})
        store.claim("r")
        with request_context.bind(request_id="r", session_id="a"):
            raw = brain.execute("r", call("save_memory", {"content": "個人の記憶"}), {"content": "個人の記憶"})
        with db.get_connection() as connection:
            rows = connection.execute("SELECT * FROM memory").fetchall()
            if rows:
                self.assertEqual(rows[0]["visibility"], "local_only")
            else:
                self.assertIn("private_memory_storage_unavailable", raw)

    def test_restart_restores_approval_and_consumes_it_once(self):
        args = {"title": "発表", "start_time": "2026-11-02T10:00:00+09:00"}
        result, _ = self.turn([{"tool_calls": [call("add_schedule", args)]}])
        self.assertEqual(result["status"], "waiting_approval")
        approval_id = result["pending_actions"][0]["approval_id"]
        store.recover()
        with patch.object(brain.lmstudio_client, "chat_completion", return_value={"content": "予定を登録したよ。"}):
            decided = api.decide(approval_id, True)
            replay = api.decide(approval_id, True)
        self.assertEqual(decided["status"], "completed")
        self.assertEqual(decided["reply"], replay["reply"])
        with db.get_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM calendar_events_cache").fetchone()[0], 1)

    def test_unknown_external_effect_is_not_automatically_retried(self):
        store.create_thread("a")
        store.accept("a", "r", {"message": "実行"})
        store.claim("r")
        store.begin_effect("r", call("add_schedule"), {})
        store.recover()
        with patch.object(tools, "dispatch", side_effect=AssertionError("replayed effect")):
            raw = brain.execute("r", call("add_schedule"), {})
        self.assertIn("effect_result_unknown", raw)
        self.assertEqual(store.result("r")["status"], "interrupted")
        self.assertTrue(store.result("r")["error"])
        self.assertEqual(store.result("r")["effects"][0]["status"], "unknown")

    def test_memory_context_has_five_items_but_storage_is_unbounded(self):
        for i in range(14):
            tools.dispatch("save_memory", {"content": f"独立した記録番号 {i}"})
        with db.get_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM memory").fetchone()[0], 14)
        packet = json.loads(brain.compact(json.dumps({
            "memories": list(range(8)), "episodes": list(range(8)), "vault_notes": list(range(8))
        }), "search_memory"))
        self.assertEqual(sum(len(packet[k]) for k in ("memories", "episodes", "vault_notes")), 5)

    def test_cancel_before_execution_does_not_call_model(self):
        store.create_thread("a")
        store.accept("a", "r", {"message": "始めて"})
        self.assertEqual(api.cancel_turn("r")["status"], "cancelled")
        with patch.object(brain.lmstudio_client, "chat_completion", side_effect=AssertionError("cancelled model")):
            self.assertEqual(api.process("r")["status"], "cancelled")

    def test_native_protocol_preserves_reasoning_and_every_tool_result(self):
        responses = [
            {"reasoning_content": "reason", "tool_calls": [call("get_current_time", call_id="a"),
                                                           call("execute_agent_write", call_id="b")]},
            {"content": "時刻を確認したよ"},
        ]
        _, model = self.turn(responses)
        messages = model.call_args.args[0]
        self.assertEqual(next(m for m in messages if m.get("reasoning_content"))["reasoning_content"], "reason")
        self.assertEqual({m["tool_call_id"] for m in messages if m["role"] == "tool"}, {"a", "b"})
        self.assertIn("tool_not_public", next(m["content"] for m in messages if m.get("tool_call_id") == "b"))

    def test_existing_database_backup_preserves_ids_and_null_session(self):
        other = Path(self.temp.name) / "old.db"
        with patch.object(config, "DB_PATH", other):
            db.init_db()
            conv_id = db.save_conversation("以前の入力", "以前の出力")
            store.ensure_schema()
            backup = Path(str(other) + ".before-renaissance.bak")
            self.assertTrue(backup.exists())
            with closing(sqlite3.connect(backup)) as connection:
                self.assertEqual(connection.execute("SELECT id,session_id FROM conversations").fetchone(), (conv_id, None))
            store.ensure_schema()
            self.assertEqual(db.recent_conversations()[0]["id"], conv_id)

    def test_shared_http_adapter_ignores_client_supplied_history(self):
        from backend.app import create_app
        from backend import lifecycle
        with patch.object(lifecycle, "startup", store.recover), patch.object(lifecycle, "shutdown"), TestClient(create_app()) as client, patch.object(
            brain.lmstudio_client, "chat_completion", return_value={"content": "確認したよ"}
        ) as model:
            response = client.post("/api/chat", json={
                "message": "この相談", "request_id": "http", "session_id": "http-thread",
                "history": [{"role": "user", "content": "別スレッドを勝手に注入"}]})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["thread_id"], "http-thread")
            self.assertNotIn("勝手に注入", json.dumps(model.call_args.args[0], ensure_ascii=False))
            self.assertEqual(client.get("/api/turns/http").json()["reply"], "確認したよ")


if __name__ == "__main__":
    unittest.main()
