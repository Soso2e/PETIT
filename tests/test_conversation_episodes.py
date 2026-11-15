import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import chroma_client, config, db, summarizer
from backend.tools import memory


class ConversationEpisodeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "petit.sqlite3"
        self.db_patch = patch.object(config, "DB_PATH", self.db_path)
        self.db_patch.start()
        db.init_db()

    def tearDown(self):
        self.db_patch.stop()
        self.tmp.cleanup()

    def _turns(self, count=2, session="s1"):
        for i in range(count):
            db.save_conversation(f"PETITの改善 {i}", f"回答 {i}", session_id=session)

    def _valid(self, title="PETIT改善"):
        return {"content": '{"title":"' + title + '","summary":"会話記憶をエピソード化する方針を確認した。","decisions":["会話記憶は3層に分ける"],"facts":["SQLiteを正本にする"],"work_in_progress":["増分Embeddingを実装中"],"next_action":["自動テストを追加する"]}'}

    def test_turns_become_one_episode_and_not_twice(self):
        self._turns(3)
        with patch.object(summarizer, "chat_completion", return_value=self._valid()), patch.object(chroma_client, "sync_structured_data", return_value={}):
            first = summarizer.summarize_pending(force=True)
            second = summarizer.summarize_pending(force=True)
        self.assertTrue(first["summarized"])
        self.assertFalse(second["summarized"])
        self.assertEqual(len(db.recent_episodes()), 1)

    def _memories(self):
        return [(row["type"], row["source"], row["content"]) for row in db.all_memory()]

    def _with_durable(self, durable):
        return {"content": self._valid()["content"][:-1] + ',"durable_knowledge":' + durable + "}"}

    def test_episode_state_stays_in_the_episode_and_is_not_promoted(self):
        self._turns(3)
        with patch.object(summarizer, "chat_completion", return_value=self._valid()), patch.object(chroma_client, "sync_structured_data", return_value={}):
            result = summarizer.summarize_pending(force=True)
        self.assertEqual(result["memories_saved"], 0)
        self.assertEqual(self._memories(), [])
        episode = db.recent_episodes()[0]
        self.assertIn("SQLiteを正本にする", episode["facts"])
        self.assertIn("増分Embeddingを実装中", episode["work_in_progress"])

    def test_only_labelled_durable_knowledge_becomes_memory(self):
        self._turns(3)
        reply = self._with_durable(
            '[{"kind":"preference","text":"ユーザーはコーヒーは浅煎りが好き"},'
            '{"kind":"profile","text":"ユーザーの猫の名前はもなか"},'
            '"今日のタスクは11件ある",'
            '{"kind":"state","text":"Notion同期は正常で競合はない"},'
            '{"kind":"fact","text":"短い"}]')
        with patch.object(summarizer, "chat_completion", return_value=reply), patch.object(chroma_client, "sync_structured_data", return_value={}):
            result = summarizer.summarize_pending(force=True)
        self.assertEqual(result["memories_saved"], 2)
        self.assertEqual(self._memories(), [("preference", "auto_knowledge", "ユーザーはコーヒーは浅煎りが好き"),
                                            ("profile", "auto_knowledge", "ユーザーの猫の名前はもなか")])

    def test_durable_knowledge_is_capped_per_episode(self):
        self._turns(3)
        reply = self._with_durable(
            "[" + ",".join('{"kind":"fact","text":"ユーザーの長く続く事実その%d"}' % i for i in range(9)) + "]")
        with patch.object(summarizer, "chat_completion", return_value=reply), patch.object(chroma_client, "sync_structured_data", return_value={}):
            result = summarizer.summarize_pending(force=True)
        self.assertEqual(result["memories_saved"], summarizer.MAX_DURABLE_PER_EPISODE)

    def test_llm_or_json_failure_keeps_turns_pending(self):
        self._turns()
        with patch.object(summarizer, "chat_completion", return_value={"content": "not json"}):
            result = summarizer.summarize_pending(force=True)
        self.assertEqual(result["reason"], "invalid_json")
        self.assertEqual(len(db.pending_episode_groups()[0]), 2)

    def test_empty_episode_is_not_saved_or_promoted(self):
        self._turns()
        empty = {"content": '{"title":"雑談","summary":"","decisions":[],"facts":[],"work_in_progress":[],"next_action":[]}'}
        with patch.object(summarizer, "chat_completion", return_value=empty):
            result = summarizer.summarize_pending(force=True)
        self.assertEqual(result["reason"], "empty_episode")
        self.assertEqual(db.all_memory(), [])

    def test_explicit_memory_is_labeled_and_normalized_duplicate_is_not_created(self):
        with patch.object(chroma_client, "sync_structured_data", return_value={}):
            first = memory.save_memory("  コーヒー は 苦手  ", "preference")
            second = memory.save_memory("コーヒー は 苦手", "preference")
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        row = db.all_memory()[0]
        self.assertEqual(row["source"], "explicit")

    def test_incremental_index_skips_unchanged_and_reindexes_model_change(self):
        memory_id, _ = db.save_memory_item("PETITの制約を覚える", "fact", "auto_episode")
        rows = db.all_memory()
        captured = []
        def fake_add(_collection, docs):
            captured.append(docs)
            return len(docs)
        with patch.object(chroma_client, "_existing_metadata", return_value={}), patch.object(chroma_client, "add_many", side_effect=fake_add):
            chroma_client.sync_structured_data(rows, [])
        metadata = captured[0][0][2]
        with patch.object(chroma_client, "_existing_metadata", return_value={f"mem_{memory_id}": metadata}), patch.object(chroma_client, "add_many", side_effect=fake_add) as add:
            chroma_client.sync_structured_data(db.all_memory(), [])
            self.assertFalse(add.called)
        with patch.object(config, "EMBED_MODEL", "changed-model"), patch.object(chroma_client, "_existing_metadata", return_value={f"mem_{memory_id}": metadata}), patch.object(chroma_client, "add_many", side_effect=fake_add) as add:
            chroma_client.sync_structured_data(db.all_memory(), [])
            self.assertTrue(add.called)

    def test_episode_search_is_primary_and_vault_search_is_kept(self):
        episode = [{"id": "episode_1", "document": "PETIT改善の決定", "distance": 0.1, "metadata": {"title": "PETIT改善", "started_at": "2026-07-14"}}]
        vault = [{"id": "vault_1", "document": "BRAINのPETITノート", "distance": 0.2, "metadata": {"relative_path": "20_Projects/PETIT.md"}}]
        with patch.object(chroma_client, "query", side_effect=[[], episode, vault]):
            result = memory.search_memory("PETIT", include_vault=True)
        self.assertEqual(result["episodes"][0]["title"], "PETIT改善")
        self.assertEqual(result["vault_notes"][0]["relative_path"], "20_Projects/PETIT.md")


if __name__ == "__main__":
    unittest.main()
