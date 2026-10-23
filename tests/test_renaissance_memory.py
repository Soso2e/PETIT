from __future__ import annotations

import json
import sqlite3
from contextlib import closing
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from backend import chroma_client, config, conversation_search as search, daily_index, db, request_context, tools
from backend.tools import memory


class RenaissanceMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        p = patch.object(config, "DB_PATH", Path(self.temp.name) / "app.db")
        p.start()
        self.addCleanup(p.stop)
        db.init_db()
        with db.get_connection() as connection:
            connection.execute("CREATE TABLE threads(id TEXT PRIMARY KEY,source TEXT,privacy TEXT,created_at TEXT)")
            connection.executemany("INSERT INTO threads VALUES(?,?,?,?)", [
                ("web", "web", "standard", db.now_iso()), ("desktop", "desktop", "standard", db.now_iso()),
                ("discord", "discord", "standard", db.now_iso()), ("private", "desktop", "local_only", db.now_iso())])
        for target in ("add", "delete_ids", "query"):
            p = patch.object(chroma_client, target, return_value=None)
            p.start()
            self.addCleanup(p.stop)
        tools.register_builtin_tools()

    def test_cross_thread_original_input_output_provenance_and_separate_current_history(self):
        first = db.save_conversation("卒研は敵AIを調べる", "実装は未確認", session_id="discord")
        second = db.save_conversation("卒研を再開したい", "まず前の決定を調べよう", session_id="web")
        with request_context.bind(request_id="q", session_id="desktop"):
            result = json.loads(tools.dispatch("search_conversations", {"query": "卒研"}))
        self.assertEqual({r["conversation_id"] for r in result["matches"]}, {first, second})
        source = next(r for r in result["matches"] if r["conversation_id"] == first)
        self.assertEqual(source["source"], "discord")
        self.assertEqual(source["thread_id"], "discord")
        self.assertEqual(source["input"], "卒研は敵AIを調べる")
        self.assertEqual(source["output"], "実装は未確認")
        self.assertTrue(source["timestamp"])
        self.assertEqual(db.recent_conversations(session_id="desktop"), [])

    def test_output_and_input_search_are_both_available(self):
        db.save_conversation("相談の入力", "出力だけに現れる決定", session_id="web")
        self.assertEqual(search.search("決定", role="user")["total_count"], 0)
        self.assertEqual(search.search("決定", role="assistant")["total_count"], 1)

    def test_utterance_source_overrides_thread_creation_surface(self):
        row = db.save_conversation("Desktopからの卒研相談", "確認", session_id="web")
        with db.get_connection() as connection:
            connection.execute("UPDATE conversations SET source='desktop' WHERE id=?", (row,))
        result = search.search("卒研", source="desktop")
        self.assertEqual(result["total_count"], 1)
        self.assertEqual(result["matches"][0]["source"], "desktop")
        self.assertEqual(result["matches"][0]["thread_id"], "web")
        self.assertEqual(result["matches"][0]["source_basis"], "utterance")
        self.assertEqual(search.search("卒研", source="web")["total_count"], 0)

    def test_literal_search_and_paging_do_not_turn_percent_into_all_history(self):
        for i in range(7):
            db.save_conversation("卒研 " + str(i), "返答", session_id="web")
        db.save_conversation("完了率50%", "割合", session_id="web")
        result = search.search("卒研", limit=3)
        self.assertEqual(len(result["matches"]), 3)
        self.assertTrue(result["has_more"])
        self.assertEqual(len(search.search("卒研", limit=3, offset=6)["matches"]), 1)
        self.assertEqual(search.search("%")["total_count"], 1)
        self.assertIn("query_required", search.search("")["error"])

    def test_legacy_null_thread_is_not_invented_and_internal_events_are_not_user_quotes(self):
        row = db.save_conversation("古い卒研の会話", "当時の返答")
        db.save_conversation("[PETIT_INTERNAL_EVENT] 卒研", "内部応答", session_id="web")
        result = search.search("卒研")
        self.assertEqual(result["total_count"], 1)
        self.assertEqual(result["matches"][0]["conversation_id"], row)
        self.assertTrue(result["matches"][0]["legacy_thread_unknown"])
        self.assertIsNone(result["matches"][0]["thread_id"])

    def test_private_source_is_never_returned_to_standard_thread_even_if_explicit_id(self):
        db.save_conversation("秘密の卒研", "私的な返答", session_id="private")
        with request_context.bind(request_id="q", session_id="web"):
            self.assertEqual(search.search("卒研", thread_id="private")["total_count"], 0)
        with request_context.bind(request_id="q", session_id="private"):
            self.assertEqual(search.search("卒研")["total_count"], 1)

    def test_storage_has_no_fixed_cap_and_concurrent_exact_duplicates_are_one_row(self):
        for i in range(35):
            memory.save_memory("別の長期記憶 " + str(i))
        with ThreadPoolExecutor(2) as executor:
            result = list(executor.map(lambda _: memory.save_memory("同一の新しい記憶"), range(2)))
        self.assertEqual(sum(r["created"] for r in result), 1)
        with db.get_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM memory").fetchone()[0], 36)

    def test_legacy_backup_precedes_memory_extension_and_preserves_content(self):
        legacy = Path(self.temp.name) / "legacy.db"
        with closing(sqlite3.connect(legacy)) as connection:
            connection.executescript(db.SCHEMA)
            connection.execute("INSERT INTO memory(created_at,type,content) VALUES(?,?,?)",
                               (db.now_iso(), "fact", "以前からの記憶"))
            connection.commit()
        with patch.object(config, "DB_PATH", legacy):
            db.init_db()
            backup = Path(str(legacy) + ".before-renaissance.bak")
            original = backup.read_bytes()
            db.init_db()
            self.assertEqual(backup.read_bytes(), original)
            with closing(sqlite3.connect(backup)) as connection:
                self.assertNotIn("visibility", {r[1] for r in connection.execute("PRAGMA table_info(memory)")})
                self.assertEqual(connection.execute("SELECT id,content FROM memory").fetchone(), (1, "以前からの記憶"))
            with db.get_connection() as connection:
                self.assertEqual(connection.execute("SELECT id,content,visibility FROM memory").fetchone()["visibility"], "standard")

    def test_superseded_and_expired_records_are_preserved_but_not_current_facts(self):
        old = memory.save_memory("卒研の発表日は11月2日")
        replacement = memory.save_memory("卒研の発表日は11月4日", replaces_id=old["id"])
        expired = memory.save_memory("卒研の仮予定", valid_until="2020-01-01T00:00:00+09:00")
        result = memory.search_memory("卒研", include_vault=False)
        self.assertEqual([m["id"] for m in result["memories"]], [replacement["id"]])
        history = memory.search_memory("卒研", include_vault=False, include_inactive=True)
        self.assertEqual(len(history["memories"]), 3)
        with db.get_connection() as connection:
            self.assertEqual(connection.execute("SELECT superseded_by FROM memory WHERE id=?", (old["id"],)).fetchone()[0], replacement["id"])
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM memory").fetchone()[0], 3)

    def test_failed_replacement_rolls_back_the_new_record(self):
        old = memory.save_memory("古い発表日")
        memory.save_memory("新しい発表日", replaces_id=old["id"])
        with self.assertRaises(ValueError):
            memory.save_memory("競合する訂正", replaces_id=old["id"])
        with db.get_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM memory").fetchone()[0], 2)

    def test_private_memory_is_not_embedded_or_returned_to_cloud_context(self):
        with request_context.bind(request_id="save", session_id="private"):
            record = memory.save_memory("非公開の発表準備")
        self.assertEqual(record["visibility"], "local_only")
        chroma_client.add.assert_not_called()
        with request_context.bind(request_id="q", session_id="web"):
            self.assertFalse(memory.search_memory("発表", include_vault=False)["memories"])
        chroma_client.query.reset_mock()
        with request_context.bind(request_id="q", session_id="private"):
            self.assertEqual(memory.search_memory("発表", include_vault=False)["memories"][0]["id"], record["id"])
        chroma_client.query.assert_not_called()

    def test_stale_semantic_hit_cannot_resurrect_a_superseded_fact(self):
        old = memory.save_memory("旧発表日")
        new = memory.save_memory("新発表日", replaces_id=old["id"])
        chroma_client.query.return_value = [{"id": f"mem_{old['id']}", "document": "旧発表日", "distance": 0.1, "metadata": {}}]
        result = memory.search_memory("発表", include_vault=False)
        self.assertNotIn(old["id"], [m["id"] for m in result["memories"]])

    def test_original_long_message_can_be_read_in_bounded_chunks_by_id(self):
        text = "前半" * 1000 + "元の決定"
        row_id = db.save_conversation(text, "返答", session_id="discord")
        first = search.search("元の決定")["matches"][0]
        self.assertTrue(first["input_truncated"])
        later = search.search(conversation_id=row_id, text_offset=first["next_text_offset"])["matches"][0]
        self.assertIn("元の決定", later["input"])
        self.assertEqual(later["input_role"], "user")

    def test_exact_same_local_calendar_payload_is_not_inserted_twice(self):
        from backend import calendar_providers
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(2) as executor:
            results = list(executor.map(lambda _: calendar_providers.add_event(
                title="卒研発表", start_time="2026-11-02T10:00:00+09:00"), range(2)))
        self.assertEqual(sum(r.get("already_exists", False) for r in results), 1)
        with db.get_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM calendar_events_cache").fetchone()[0], 1)

    def test_multiple_keywords_and_japanese_related_candidates_keep_the_original_id(self):
        record = memory.save_memory("卒研発表の日時は2026年11月10日10時")
        multi = memory.search_memory("卒研 発表", include_vault=False)
        self.assertEqual(multi["memories"][0]["id"], record["id"])
        related = memory.search_memory("卒研の発表日", include_vault=False)
        self.assertEqual(related["memories"][0]["id"], record["id"])
        self.assertEqual(related["memories"][0]["match_kind"], "related_candidate")

    def test_legacy_unhashed_memory_is_reused_without_deleting_or_replacing_its_row(self):
        with db.get_connection() as connection:
            row_id = connection.execute(
                "INSERT INTO memory(created_at,type,content) VALUES(?,?,?)",
                (db.now_iso(), "note", "以前からある記憶")).lastrowid
        db.init_db()
        reused = memory.save_memory("以前からある記憶")
        self.assertFalse(reused["created"])
        self.assertEqual(reused["id"], row_id)


if __name__ == "__main__":
    unittest.main()
