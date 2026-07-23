from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from backend import config, daily_index, db, worker


class DailyLifeIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.patches = [
            patch.object(config, "DB_PATH", root / "app.db"),
            patch.object(config, "AI_DAILY_DIR", root / "daily"),
            patch.object(config, "CHROMA_PATH", root / "chroma"),
            patch.object(config, "DAILY_INDEX_TIMEZONE", "Asia/Tokyo"),
            patch.object(config, "DAILY_INDEX_HOUR", 0),
            patch.object(config, "DAILY_INDEX_MINUTE", 10),
            patch.object(config, "DAILY_INDEX_MAX_INPUT_CHARS", 12000),
            patch.object(config, "DAILY_INDEX_ASSISTANT_MAX_CHARS", 240),
            patch.object(config, "DAILY_INDEX_CATCHUP_DAYS", 7),
        ]
        for item in self.patches:
            item.start()
        db.init_db()
        daily_index.ensure_schema()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    @staticmethod
    def _insert(timestamp: str, user: str, assistant: str, session_id: str) -> int:
        with db.get_connection() as conn:
            cur = conn.execute(
                "INSERT INTO conversations(timestamp, user_text, assistant_text, used_tools, session_id) "
                "VALUES (?, ?, ?, NULL, ?)",
                (timestamp, user, assistant, session_id),
            )
            return int(cur.lastrowid)

    def test_due_day_waits_until_configured_local_time(self) -> None:
        before = datetime(2026, 7, 22, 15, 9, tzinfo=timezone.utc)   # 00:09 JST
        after = datetime(2026, 7, 22, 15, 10, tzinfo=timezone.utc)   # 00:10 JST
        self.assertEqual(daily_index.due_day(before).isoformat(), "2026-07-21")
        self.assertEqual(daily_index.due_day(after).isoformat(), "2026-07-22")

    def test_noise_filter_only_drops_certain_noise_and_consecutive_duplicates(self) -> None:
        rows = [
            {"id": 1, "timestamp": "t", "user_text": "✨", "assistant_text": "", "used_tools": None, "session_id": "a"},
            {"id": 2, "timestamp": "t", "user_text": "うん", "assistant_text": "了解", "used_tools": None, "session_id": "a"},
            {"id": 3, "timestamp": "t", "user_text": "うん", "assistant_text": "了解", "used_tools": None, "session_id": "b"},
            {"id": 4, "timestamp": "t", "user_text": "喧嘩", "assistant_text": "", "used_tools": None, "session_id": "b"},
        ]
        compact = daily_index._compact_rows(rows)
        self.assertEqual([row["user"] for row in compact], ["うん", "喧嘩"])

    def test_generate_combines_all_devices_and_saves_searchable_daily_memory(self) -> None:
        first_id = self._insert("2026-07-22T01:00:00+00:00", "渋谷に行った", "楽しめた？", "iphone")
        second_id = self._insert("2026-07-22T11:00:00+00:00", "ラーメン食べた", "いいね", "pc")
        self._insert("2026-07-22T11:01:00+00:00", "ラーメン食べた", "いいね", "pc")
        parsed = {
            "summary": "渋谷へ行き、ラーメンを食べた。",
            "events": ["渋谷へ行った"],
            "activities": [],
            "foods": ["ラーメンを食べた"],
            "people": [],
            "places": ["渋谷"],
            "emotions": [],
            "projects": [],
            "memory_candidates": [],
            "uncertain": [],
        }
        with (
            patch.object(daily_index, "_call_local", return_value=parsed) as local,
            patch.object(daily_index.chroma_client, "sync_structured_data", return_value={"memory": 1, "episodes": 0}),
        ):
            result = daily_index.generate("2026-07-22")

        self.assertTrue(result["generated"])
        self.assertEqual(result["conversation_count"], 2)
        transcript = local.call_args.args[1]
        self.assertIn("session=iphone", transcript)
        self.assertIn("session=pc", transcript)
        self.assertIn("渋谷に行った", transcript)
        self.assertIn("ラーメン食べた", transcript)
        with db.get_connection() as conn:
            memory = conn.execute(
                "SELECT type, source, content FROM memory WHERE source = 'daily_index:2026-07-22'"
            ).fetchone()
            daily = conn.execute(
                "SELECT status, source_conversation_ids FROM daily_indexes WHERE day = '2026-07-22'"
            ).fetchone()
        self.assertEqual(memory["type"], "daily_index")
        self.assertIn("ラーメン", memory["content"])
        self.assertEqual(daily["status"], "generated")
        self.assertEqual(json.loads(daily["source_conversation_ids"]), [first_id, second_id])
        self.assertTrue((config.AI_DAILY_DIR / "2026-07-22-index.md").exists())

        with patch.object(daily_index, "_call_local") as second_call:
            repeated = daily_index.generate("2026-07-22")
        self.assertEqual(repeated["reason"], "already_indexed")
        second_call.assert_not_called()

    def test_local_failure_keeps_raw_conversations_for_retry(self) -> None:
        conv_id = self._insert("2026-07-22T03:00:00+00:00", "彼女と喧嘩した", "大丈夫？", "iphone")
        with patch.object(daily_index, "_call_local", side_effect=daily_index.DailyIndexError("offline")):
            result = daily_index.generate("2026-07-22")
        self.assertEqual(result["reason"], "local_llm_unavailable")
        with db.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM conversations WHERE id = ?", (conv_id,)).fetchone()[0]
            status = conn.execute("SELECT status FROM daily_indexes WHERE day = '2026-07-22'").fetchone()[0]
        self.assertEqual(count, 1)
        self.assertEqual(status, "failed")

    def test_call_local_uses_dedicated_local_endpoint(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "choices": [{"message": {"content": json.dumps({"summary": "ok"})}}]
        }
        with (
            patch.object(config, "DAILY_INDEX_BASE_URL", "http://127.0.0.1:1234/v1"),
            patch.object(config, "DAILY_INDEX_MODEL", "local-qwen"),
            patch.object(config, "DAILY_INDEX_API_KEY", "lm-studio"),
            patch.object(daily_index.httpx, "post", return_value=response) as post,
        ):
            result = daily_index._call_local("2026-07-22", "ユーザー: テスト")
        self.assertEqual(result["summary"], "ok")
        self.assertEqual(post.call_args.args[0], "http://127.0.0.1:1234/v1/chat/completions")
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "local-qwen")
        self.assertEqual(payload["chat_template_kwargs"], {"enable_thinking": False})

    def test_worker_starts_and_stops_daily_scheduler_when_enabled(self) -> None:
        instance = worker.JobWorker(interval_seconds=0.01)
        with (
            patch.object(config, "DAILY_INDEX_ENABLED", True),
            patch.object(worker.task_sync_queue, "ensure_task_sync_schema"),
            patch.object(worker.github_daily_review, "ensure_schema"),
            patch.object(worker.github_daily_review, "get_scheduler") as github_scheduler,
            patch.object(worker.daily_index, "ensure_schema"),
            patch.object(worker.daily_index, "get_scheduler") as daily_scheduler,
            patch("backend.tools.tasks_phase2.install_agent_routes"),
        ):
            instance.start()
            instance.stop()
        github_scheduler.return_value.start.assert_called_once()
        github_scheduler.return_value.stop.assert_called_once()
        daily_scheduler.return_value.start.assert_called_once()
        daily_scheduler.return_value.stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
