from __future__ import annotations

import json
import unittest
import tempfile
import sqlite3
from pathlib import Path
from unittest.mock import Mock, patch

from backend import config, lmstudio_client, main, vault_indexer
from backend.notion_client import NotionError
from backend.tools import brain
from backend.tools import tasks as task_tools


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
