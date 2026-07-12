from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend import agent, config, model_router, vault_indexer


class ModelRoutingTests(unittest.TestCase):
    def test_simple_and_agent_routes(self) -> None:
        self.assertEqual(model_router.choose("やっほー")["kind"], "chat")
        self.assertEqual(model_router.choose("今日何をすればいい？")["kind"], "agent")
        self.assertEqual(model_router.choose("a" * (config.AGENT_MESSAGE_CHARS + 1))["kind"], "agent")

        self.assertEqual(model_router.choose("今何時？")["kind"], "agent")

    def test_greeting_returns_without_model_call(self) -> None:
        with patch.object(agent, "chat_completion") as fake_chat:
            result = agent.run("PETITこんばんわ")

        fake_chat.assert_not_called()
        self.assertEqual(result["model_route"]["kind"], "instant")
        self.assertEqual(result["model_route"]["reasons"], ["instant_greeting"])
        self.assertIn("こんばんは", result["reply"])

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
            patch.object(agent.recall, "build_recall_block", recall),
            patch.object(agent.situation, "build_context_block", return_value=""),
        ):
            result = agent.run("最近どう？")
        self.assertEqual(result["model_route"]["kind"], "chat")
        self.assertEqual(calls[0], {"tools": None, "model": "chat-test"})
        recall.assert_not_called()

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
        self.assertEqual(result["model_route"]["kind"], "chat")
        self.assertEqual(calls[0]["model"], "chat-test")
        self.assertTrue(calls[0]["tools"])
        names = {item["function"]["name"] for item in calls[0]["tools"]}
        self.assertEqual(names, {"get_tasks"})
        self.assertEqual(len(calls), 1)

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
        ):
            result = agent.run("今日のタスクを確認して")

        self.assertEqual(calls[0]["model"], "chat-test")
        self.assertFalse(result["model_route"].get("deferred", False))
        self.assertNotEqual(result["used_tools"][0]["name"] if result["used_tools"] else None, "agent_followup")


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


if __name__ == "__main__":
    unittest.main()
