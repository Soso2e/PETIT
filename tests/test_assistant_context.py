from __future__ import annotations

import unittest
import tempfile
import sqlite3
from pathlib import Path
from unittest.mock import Mock, patch

from backend import agent, config, lmstudio_client, main, model_router, vault_indexer
from backend.notion_client import NotionError
from backend.tools import brain
from backend.tools import tasks as task_tools


class ModelRoutingTests(unittest.TestCase):
    def test_simple_and_agent_routes(self) -> None:
        self.assertEqual(model_router.choose("やっほー")["kind"], "chat")
        self.assertEqual(model_router.choose("今日何をすればいい？")["kind"], "agent")
        self.assertEqual(model_router.choose("a" * (config.AGENT_MESSAGE_CHARS + 1))["kind"], "agent")

        self.assertEqual(model_router.choose("今何時？")["kind"], "agent")

    def test_greeting_uses_one_chat_model_call_without_tools(self) -> None:
        with patch.object(agent, "chat_completion", return_value={"role": "assistant", "content": "こんばんは"}) as fake_chat:
            result = agent.run("PETITこんばんわ")

        fake_chat.assert_called_once()
        self.assertEqual(result["model_route"]["kind"], "chat")
        self.assertEqual(result["model_route"]["model"], config.CHAT_MODEL)
        self.assertEqual(result["used_tools"], [])

    def test_orphan_assistant_opener_is_not_sent_to_lmstudio(self) -> None:
        with patch.object(agent, "chat_completion", return_value={"role": "assistant", "content": "大丈夫？"}) as fake_chat:
            agent.run("眠い", history=[{"role": "assistant", "content": "こんにちは"}])

        sent = fake_chat.call_args.args[0]
        self.assertEqual([item["role"] for item in sent], ["system", "user"])

    def test_chat_model_does_not_receive_tools(self) -> None:
        calls = []
        recall = Mock(return_value="")

        def fake_chat(messages, tools=None, temperature=None, model=None):
            calls.append({"tools": tools, "model": model})
            return {"role": "assistant", "content": "こんにちは"}

        with (
            patch.object(config, "CHAT_MODEL", "chat-test"),
            patch.object(config, "AGENT_MODEL", "agent-test"),
            patch.object(config, "DEFER_AGENT_JOBS", False),
            patch.object(agent, "chat_completion", side_effect=fake_chat),
            patch.object(agent.tools, "dispatch", return_value='{"count":0,"tasks":[]}'),
            patch.object(agent.recall, "build_recall_block", recall),
            patch.object(agent.situation, "build_context_block", return_value=""),
        ):
            result = agent.run("最近どう？")
        self.assertEqual(result["model_route"]["kind"], "chat")
        self.assertEqual(calls[0], {"tools": None, "model": "chat-test"})
        recall.assert_not_called()

    def test_empty_length_answer_retries_once(self) -> None:
        calls = []

        def fake_chat(messages, tools=None, temperature=None, model=None):
            calls.append({"tools": tools, "model": model})
            if len(calls) == 1:
                return {"role": "assistant", "content": "", "_finish_reason": "length"}
            return {"role": "assistant", "content": "少し休もう"}

        with patch.object(agent, "chat_completion", side_effect=fake_chat):
            result = agent.run("ねむい")

        self.assertEqual(result["reply"], "少し休もう")
        self.assertEqual(len(calls), 2)
        self.assertIsNone(calls[1]["tools"])

    def test_explicit_request_receives_only_related_tools(self) -> None:
        calls = []

        def fake_chat(messages, tools=None, temperature=None, model=None):
            calls.append({"tools": tools, "model": model})
            return {"role": "assistant", "content": "確認したよ"}

        with (
            patch.object(config, "CHAT_MODEL", "chat-test"),
            patch.object(config, "AGENT_MODEL", "agent-test"),
            patch.object(config, "DEFER_AGENT_JOBS", False),
            patch.object(agent, "chat_completion", side_effect=fake_chat),
            patch.object(agent.recall, "build_recall_block", return_value=""),
            patch.object(agent.situation, "build_context_block", return_value=""),
        ):
            result = agent.run("今日のタスクを確認して")
        self.assertEqual(result["model_route"]["kind"], "forced_read")
        self.assertEqual(calls[0]["model"], "agent-test")
        self.assertIsNone(calls[0]["tools"])
        self.assertEqual(result["used_tools"][0]["name"], "get_tasks")
        self.assertEqual(len(calls), 1)

    def test_incomplete_task_read_is_not_misrouted_as_completion(self) -> None:
        with (
            patch.object(agent, "chat_completion", return_value={"role": "assistant", "content": "3件あるよ"}),
            patch.object(agent.tools, "dispatch", return_value='{"count":3,"tasks":[]}') as dispatch,
        ):
            result = agent.run("未完了のNotionタスクを3件だけ教えて")

        dispatch.assert_called_once()
        self.assertEqual(result["used_tools"][0]["name"], "get_tasks")

    def test_natural_planning_consultation_exposes_bounded_sources(self) -> None:
        with (
            patch.object(agent, "chat_completion", return_value={"role": "assistant", "content": "整理するね"}) as fake_chat,
            patch.object(agent.tools, "dispatch", return_value='{"ok":true}') as dispatch,
        ):
            result = agent.run("今日何からやる？")

        self.assertIsNone(fake_chat.call_args.kwargs["tools"])
        self.assertEqual([call.args[0] for call in dispatch.call_args_list], ["get_tasks", "get_schedule", "search_brain_notes"])
        self.assertEqual(result["model_route"]["kind"], "planning")

    def test_explicit_brain_search_uses_non_embedding_tool(self) -> None:
        with (
            patch.object(agent, "chat_completion", return_value={"role": "assistant", "content": "探すね"}) as fake_chat,
            patch.object(agent.tools, "dispatch", return_value='{"count":0,"vault_notes":[]}') as dispatch,
        ):
            result = agent.run("BRAINからPETITの構成を探して")

        self.assertIsNone(fake_chat.call_args.kwargs["tools"])
        dispatch.assert_called_once()
        self.assertEqual(result["used_tools"][0]["name"], "search_brain_notes")

    def test_brain_path_edit_intent_includes_search_and_write(self) -> None:
        with patch.object(agent, "chat_completion", return_value={"role": "assistant", "content": ""}):
            result = agent.run("BRAINのPETIT/Daily/test.mdに確認と追記して")

        self.assertFalse(result["persist"])
        self.assertIn("安全な変更案", result["reply"])

    def test_explicit_brain_append_is_proposed_without_llm(self) -> None:
        with patch.object(agent, "chat_completion") as chat:
            result = agent.run("BRAINの「PETIT/Daily/test.md」に「確認済み」と追記して")

        chat.assert_not_called()
        action = result["pending_actions"][0]
        self.assertEqual(action["arguments"]["relative_path"], "PETIT/Daily/test.md")
        self.assertEqual(action["arguments"]["content"], "確認済み")

    def test_write_tool_is_proposed_without_dispatch(self) -> None:
        tool_call = {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call-write",
                "type": "function",
                "function": {"name": "create_task", "arguments": '{"title":"請求書を出す"}'},
            }],
        }
        with (
            patch.object(agent, "chat_completion", return_value=tool_call),
            patch.object(agent.tools, "dispatch") as dispatch,
        ):
            result = agent.run("請求書を出すタスクを作って")

        dispatch.assert_not_called()
        self.assertEqual(result["pending_actions"][0]["name"], "create_task")
        self.assertIn("実行しますか", result["reply"])

    def test_brain_search_can_continue_to_confirmed_edit(self) -> None:
        replies = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call-search",
                    "type": "function",
                    "function": {"name": "search_brain_notes", "arguments": '{"query":"PETIT"}'},
                }],
            },
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call-edit",
                    "type": "function",
                    "function": {
                        "name": "edit_brain_note",
                        "arguments": '{"relative_path":"PETIT/Daily/test.md","mode":"append","content":"確認"}',
                    },
                }],
            },
        ]
        with (
            patch.object(agent, "chat_completion", side_effect=replies),
            patch.object(agent.tools, "dispatch", return_value='{"count":1,"vault_notes":[]}') as dispatch,
        ):
            result = agent.run("BRAINのPETIT/Daily/test.mdに確認と追記して")

        dispatch.assert_called_once()
        self.assertEqual(result["pending_actions"][0]["name"], "edit_brain_note")

    def test_tool_failure_is_not_persistable(self) -> None:
        replies = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call-read",
                    "type": "function",
                    "function": {"name": "get_tasks", "arguments": "{}"},
                }],
            },
            {"role": "assistant", "content": "タスク取得に失敗したよ"},
        ]
        with (
            patch.object(agent, "chat_completion", side_effect=replies),
            patch.object(agent.tools, "dispatch", return_value='{"error":"offline"}'),
        ):
            result = agent.run("今日のタスクを確認して")

        self.assertFalse(result["persist"])

    def test_tool_results_are_returned_as_user_followup_for_lmstudio_templates(self) -> None:
        calls = []

        def fake_chat(messages, tools=None, temperature=None, model=None):
            calls.append({"messages": messages, "tools": tools, "model": model})
            if len(calls) == 1:
                return {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {"name": "search_news", "arguments": '{"query":"AI"}'},
                        }
                    ],
                }
            return {"role": "assistant", "content": "調べた結果だよ"}

        with (
            patch.object(config, "CHAT_MODEL", "agent-test"),
            patch.object(config, "AGENT_MODEL", "agent-test"),
            patch.object(config, "DEFER_AGENT_JOBS", False),
            patch.object(agent, "chat_completion", side_effect=fake_chat),
            patch.object(agent.tools, "dispatch", return_value='{"ok": true, "items": []}'),
            patch.object(agent.recall, "build_recall_block", return_value=""),
            patch.object(agent.situation, "build_context_block", return_value=""),
        ):
            result = agent.run("AIについて調べて")

        self.assertEqual(result["reply"], "調べた結果だよ")
        self.assertEqual(result["used_tools"], [{"name": "search_news", "arguments": '{"query":"AI"}'}])
        second_messages = calls[1]["messages"]
        self.assertFalse(any(message.get("role") == "tool" for message in second_messages))
        self.assertEqual(second_messages[-1]["role"], "user")
        self.assertIn("元の発話: AIについて調べて", second_messages[-1]["content"])
        self.assertIn("ツール: search_news", second_messages[-1]["content"])

    def test_deferable_agent_turn_is_not_queued(self) -> None:
        calls = []

        def fake_chat(messages, tools=None, temperature=None, model=None):
            calls.append({"tools": tools, "model": model})
            return {"role": "assistant", "content": "先に短く返すね"}

        with (
            patch.object(config, "CHAT_MODEL", "chat-test"),
            patch.object(config, "AGENT_MODEL", "agent-test"),
            patch.object(config, "DEFER_AGENT_JOBS", True),
            patch.object(agent, "chat_completion", side_effect=fake_chat),
            patch.object(agent.tools, "dispatch", return_value='{"count":0,"tasks":[]}'),
        ):
            result = agent.run("今日のタスクを確認して")

        self.assertEqual(calls[0]["model"], "agent-test")
        self.assertFalse(result["model_route"].get("deferred", False))
        self.assertNotEqual(result["used_tools"][0]["name"] if result["used_tools"] else None, "agent_followup")


class LLMRequestTests(unittest.TestCase):
    def test_chat_completion_rejects_messages_without_user_query(self) -> None:
        with self.assertRaises(lmstudio_client.LMStudioError):
            lmstudio_client.chat_completion([{"role": "system", "content": "test"}])

    def test_chat_completion_disables_thinking_and_keeps_finish_reason(self) -> None:
        response = Mock()
        response.json.return_value = {
            "choices": [{
                "message": {"role": "assistant", "content": ""},
                "finish_reason": "length",
            }]
        }
        response.raise_for_status.return_value = None
        with patch.object(lmstudio_client.httpx, "post", return_value=response) as post:
            result = lmstudio_client.chat_completion([{"role": "user", "content": "ねむい"}])

        payload = post.call_args.kwargs["json"]
        self.assertFalse(payload["chat_template_kwargs"]["enable_thinking"])
        self.assertEqual(payload["max_tokens"], 512)
        self.assertEqual(result["_finish_reason"], "length")


class VaultSearchTests(unittest.TestCase):
    def test_ranked_japanese_search_and_private_exclusion(self) -> None:
        root = Path("vault")
        project = root / "20_Projects" / "PETIT構成.md"
        with (
            patch.object(config, "OBSIDIAN_VAULT_DIRS", [root]),
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "is_dir", return_value=True),
            patch.object(vault_indexer, "_iter_markdown_files", return_value=[project]),
            patch.object(
                vault_indexer,
                "_read_text",
                return_value="# PETITローカルLLM構成\n会話モデルとエージェントモデルを分ける。",
            ),
            patch.object(vault_indexer, "_relative_path", return_value=str(Path("20_Projects") / "PETIT構成.md")),
            patch.object(vault_indexer, "_modified_at", return_value="2026-07-12T00:00:00+00:00"),
        ):
            rows = vault_indexer.keyword_search("PETITの構成どうだっけ", limit=5)

        self.assertTrue(rows)
        self.assertEqual(rows[0]["relative_path"], str(Path("20_Projects") / "PETIT構成.md"))
        self.assertIn("_private", vault_indexer.EXCLUDED_DIR_NAMES)
        self.assertIn("_attachments", vault_indexer.EXCLUDED_DIR_NAMES)

    def test_vault_sync_does_not_probe_with_embedding_query(self) -> None:
        with (
            patch.object(config, "OBSIDIAN_VAULT_DIRS", [Path("vault")]),
            patch.object(Path, "exists", return_value=True),
            patch.object(Path, "is_dir", return_value=True),
            patch.object(vault_indexer, "_purge_excluded_chunks", return_value=0),
            patch.object(vault_indexer, "_iter_markdown_files", return_value=[]),
            patch.object(vault_indexer.chroma_client, "query") as query,
        ):
            result = vault_indexer.index_configured_vaults()

        query.assert_not_called()
        self.assertEqual(result["chunks"], 0)

    def test_vault_index_batches_changed_chunks(self) -> None:
        root = Path("vault")
        path = root / "note.md"
        chunks = [("A", "first chunk"), ("B", "second chunk")]

        with (
            patch.object(vault_indexer, "_read_text", return_value="ignored"),
            patch.object(vault_indexer, "_chunk_markdown", return_value=chunks),
            patch.object(vault_indexer, "_existing_file_chunks", return_value={}),
            patch.object(vault_indexer, "_modified_at", return_value="2026-07-12T00:00:00+00:00"),
            patch.object(vault_indexer.chroma_client, "delete_ids", return_value=True),
            patch.object(vault_indexer.chroma_client, "add_many", return_value=2) as add_many,
        ):
            result = vault_indexer._index_file(root, path)

        self.assertEqual(result, {"indexed": 2, "skipped": 0, "deleted": 0})
        add_many.assert_called_once()
        docs = add_many.call_args.args[1]
        self.assertEqual(len(docs), 2)
        self.assertTrue(all("content_hash" in doc[2] for doc in docs))

    def test_vault_index_skips_unchanged_chunk_hashes(self) -> None:
        root = Path("vault")
        path = root / "note.md"
        chunk = "unchanged chunk"
        doc_id = vault_indexer._doc_id(root, path, 0)
        existing = {doc_id: {"content_hash": vault_indexer._content_hash(chunk)}}

        with (
            patch.object(vault_indexer, "_read_text", return_value="ignored"),
            patch.object(vault_indexer, "_chunk_markdown", return_value=[("A", chunk)]),
            patch.object(vault_indexer, "_existing_file_chunks", return_value=existing),
            patch.object(vault_indexer.chroma_client, "delete_ids", return_value=True),
            patch.object(vault_indexer.chroma_client, "add_many", return_value=0) as add_many,
        ):
            result = vault_indexer._index_file(root, path)

        self.assertEqual(result, {"indexed": 0, "skipped": 1, "deleted": 0})
        add_many.assert_called_once_with(vault_indexer.COLLECTION_NAME, [])

    def test_brain_edit_is_limited_to_existing_markdown_in_vault(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            note = root / "20_Projects" / "PETIT.md"
            note.parent.mkdir()
            note.write_text("# PETIT\n", encoding="utf-8")
            with (
                patch.object(config, "OBSIDIAN_VAULT_DIRS", [root]),
                patch.object(vault_indexer, "_index_file", return_value={"indexed": 1}),
            ):
                result = brain.edit_brain_note("20_Projects/PETIT.md", "append", "次: E2E確認")
                self.assertTrue(result["updated"])
                self.assertIn("次: E2E確認", note.read_text(encoding="utf-8"))
                with self.assertRaises(ValueError):
                    brain.edit_brain_note("../outside.md", "append", "unsafe")


class PersistenceAndApprovalTests(unittest.TestCase):
    def test_empty_answer_returns_error_without_history_write(self) -> None:
        with (
            patch.object(main.agent, "run", return_value={"reply": "", "used_tools": []}),
            patch.object(main.db, "save_conversation") as save,
        ):
            response = main.chat(main.ChatRequest(message="こんにちは", request_id="req-1"))

        save.assert_not_called()
        self.assertIn("返答を生成できません", response.error)

    def test_confirmed_action_executes_exactly_once(self) -> None:
        pending = main._register_pending_actions([{"name": "create_task", "arguments": {"title": "確認テスト"}}])[0]
        with patch.object(main.tools, "dispatch", return_value='{"created":true,"source":"local"}') as dispatch:
            response = main.decide_action(pending.approval_id, main.ActionDecision(approved=True))
            second = main.decide_action(pending.approval_id, main.ActionDecision(approved=True))

        dispatch.assert_called_once_with("create_task", {"title": "確認テスト"})
        self.assertIn("実行しました", response.reply)
        self.assertIsNotNone(second.error)

    def test_all_user_data_write_tools_require_confirmation(self) -> None:
        names = {
            "add_task", "create_task", "complete_task", "add_schedule",
            "save_memory", "summarize_now", "create_handoff_note", "edit_brain_note",
        }
        self.assertTrue(all(agent.tools.requires_confirmation(name) for name in names))

    def test_notion_create_failure_does_not_fallback_to_local_write(self) -> None:
        with (
            patch.object(config, "notion_configured", return_value=True),
            patch.object(task_tools, "create_task_page", side_effect=NotionError("offline")),
            patch.object(task_tools, "_create_local_task") as create_local,
        ):
            result = task_tools.create_task("保存しないテスト")

        create_local.assert_not_called()
        self.assertFalse(result["created"])

    def test_database_context_manager_closes_connection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(config, "DB_PATH", Path(tmp) / "test.db"):
            main.db.init_db()
            with main.db.get_connection() as conn:
                conn.execute("SELECT 1").fetchone()
            with self.assertRaises(sqlite3.ProgrammingError):
                conn.execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()
