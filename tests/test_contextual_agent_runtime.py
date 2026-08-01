from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import agent_runtime, config, db, tools


def tool_call(name: str, arguments: dict | None = None, call_id: str = "call") -> dict:
    return {
        "content": "",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(arguments or {}, ensure_ascii=False),
                },
            }
        ],
    }


class ContextualAgentRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(config, "DB_PATH", Path(self.temp_dir.name) / "app.db")
        self.db_patch.start()
        db.init_db()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def route(self, capabilities: list[str]) -> dict:
        return {
            "type": "agent",
            "capabilities": capabilities,
            "goal": "ユーザーの依頼を実行する",
            "confidence": 0.98,
            "source": "llm",
        }

    def test_deferred_reply_detection_ignores_completed_and_optional_language(self) -> None:
        self.assertTrue(agent_runtime._is_deferred_action_reply("状況を確認します。"))
        self.assertFalse(agent_runtime._is_deferred_action_reply("状況を確認しました。"))
        self.assertFalse(agent_runtime._is_deferred_action_reply("概要は以上だよ。必要なら詳細も確認します。"))

    def test_list_item_request_uses_low_risk_write_without_confirmation(self) -> None:
        created = json.loads(tools.dispatch("create_list", {"name": "科学大キャンプ"}))
        self.assertTrue(created["created"])

        model_results = [
            tool_call("get_lists", call_id="lists"),
            tool_call(
                "add_list_item",
                {
                    "list_name": "科学大キャンプ",
                    "title": "iPhoneコースガイド見る",
                },
                call_id="add",
            ),
            {"content": "科学大キャンプリストに追加したよ。", "tool_calls": []},
        ]
        with patch.object(agent_runtime.capability_router, "choose", return_value=self.route(["lists_and_tasks"])):
            with patch.object(agent_runtime, "chat_completion", side_effect=model_results):
                result = agent_runtime.run(
                    "科学大キャンプリストに、iPhoneコースガイド見るって追加",
                    history=[],
                )

        self.assertNotIn("pending_actions", result)
        self.assertEqual(result["reply"], "科学大キャンプリストに追加したよ。")
        self.assertEqual(
            [item["name"] for item in result["used_tools"]],
            ["get_lists", "add_list_item"],
        )
        items = json.loads(
            tools.dispatch("get_list_items", {"list_name": "科学大キャンプ"})
        )
        self.assertEqual(items["total_count"], 1)
        self.assertEqual(items["items"][0]["title"], "iPhoneコースガイド見る")

    def test_topic_only_message_does_not_create_a_list(self) -> None:
        with patch.object(agent_runtime.capability_router, "choose", return_value=self.route(["lists_and_tasks"])):
            with patch.object(
                agent_runtime,
                "chat_completion",
                return_value={"content": "科学大キャンプについて、何を知りたい？", "tool_calls": []},
            ):
                result = agent_runtime.run("科学大キャンプについて", history=[])

        self.assertNotIn("pending_actions", result)
        self.assertIn("何を知りたい", result["reply"])
        lists = json.loads(tools.dispatch("get_lists", {}))
        self.assertEqual(lists["count"], 1)  # Built-in task list only.

    def test_agent_can_use_multiple_read_tools_before_answering(self) -> None:
        json.loads(tools.dispatch("create_list", {"name": "アニメ"}))
        model_results = [
            tool_call("get_lists", call_id="lists"),
            tool_call("get_list_items", {"list_name": "アニメ"}, call_id="items"),
            {"content": "アニメリストは空だよ。", "tool_calls": []},
        ]
        with patch.object(agent_runtime.capability_router, "choose", return_value=self.route(["lists_and_tasks"])):
            with patch.object(agent_runtime, "chat_completion", side_effect=model_results):
                result = agent_runtime.run("アニメリストの中身を教えて", history=[])

        self.assertEqual([item["name"] for item in result["used_tools"]], ["get_lists", "get_list_items"])
        self.assertEqual(result["model_route"]["tool_rounds"], 2)
        self.assertIn("空", result["reply"])

    def test_deferred_promise_is_retried_until_tool_result_is_returned(self) -> None:
        model_results = [
            {"content": "プロジェクト管理ツールを確認します。", "tool_calls": []},
            tool_call("get_project_status", call_id="project-status"),
            {"content": "進行中はPETITで、次は会話フローの確認だよ。", "tool_calls": []},
        ]
        with patch.object(agent_runtime.capability_router, "choose", return_value=self.route(["projects"])):
            with patch.object(agent_runtime, "chat_completion", side_effect=model_results):
                result = agent_runtime.run("今進んでいるプロジェクトの状況をまとめて", history=[])

        self.assertEqual(result["reply"], "進行中はPETITで、次は会話フローの確認だよ。")
        self.assertEqual([item["name"] for item in result["used_tools"]], ["get_project_status"])

    def test_repeated_deferred_promise_is_reported_as_not_executed(self) -> None:
        model_results = [
            {"content": "状況を調べます。", "tool_calls": []},
            {"content": "プロジェクトを確認します。", "tool_calls": []},
        ]
        with patch.object(agent_runtime.capability_router, "choose", return_value=self.route(["projects"])):
            with patch.object(agent_runtime, "chat_completion", side_effect=model_results):
                result = agent_runtime.run("プロジェクト状況を教えて", history=[])

        self.assertIn("実行できなかった", result["reply"])
        self.assertNotIn("確認します", result["reply"])
        self.assertFalse(result["persist"])
        self.assertEqual(result["model_route"]["fallback_reason"], "deferred_action_without_execution")

    def test_duplicate_tool_call_is_not_executed_twice(self) -> None:
        model_results = [
            tool_call("get_lists", call_id="first"),
            tool_call("get_lists", call_id="duplicate"),
            {"content": "リストを確認したよ。", "tool_calls": []},
        ]
        with patch.object(agent_runtime.capability_router, "choose", return_value=self.route(["lists_and_tasks"])):
            with patch.object(agent_runtime, "chat_completion", side_effect=model_results):
                result = agent_runtime.run("リストを確認して", history=[])

        self.assertEqual([item["name"] for item in result["used_tools"]], ["get_lists"])
        self.assertFalse(result["persist"])

    def test_progress_events_are_jobs_not_conversation_history(self) -> None:
        model_results = [
            tool_call("get_lists", call_id="lists"),
            {"content": "確認したよ。", "tool_calls": []},
        ]
        with patch.object(agent_runtime.request_context, "current_ids", return_value=("req-1", "session-1")):
            with patch.object(agent_runtime.capability_router, "choose", return_value=self.route(["lists_and_tasks"])):
                with patch.object(agent_runtime, "chat_completion", side_effect=model_results):
                    agent_runtime.run("リストを確認して", history=[])

        with db.get_connection() as conn:
            progress_count = int(
                conn.execute("SELECT COUNT(*) FROM jobs WHERE type='agent_progress'").fetchone()[0]
            )
            conversation_count = int(conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0])
        self.assertGreaterEqual(progress_count, 3)
        self.assertEqual(conversation_count, 0)


if __name__ == "__main__":
    unittest.main()
