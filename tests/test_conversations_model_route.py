from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import config, conversation_store, db


class RecentConversationsModelRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(config, "DB_PATH", Path(self.temp_dir.name) / "petit.db")
        self.db_patch.start()
        db.init_db()
        conversation_store.ensure_schema()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_recent_conversations_attaches_model_route_from_turns(self) -> None:
        conversation_store.create_thread("test-session")
        with db.get_connection() as conn:
            # 1. Insert conversation
            cursor = conn.execute(
                "INSERT INTO conversations(timestamp, user_text, assistant_text, session_id, source) "
                "VALUES (?, ?, ?, ?, ?)",
                (db.now_iso(), "こんにちは", "お疲れさまです", "test-session", "web"),
            )
            conv_id = cursor.lastrowid

            # 2. Insert turn pointing to this conversation
            model_route = {
                "actual_route": "chat",
                "kind": "brain",
                "provider": "antigravity_cli",
                "model": "gemini-3.8-flash-low",
            }
            result_json = json.dumps({"model_route": model_route})
            conn.execute(
                "INSERT INTO turns(request_id, thread_id, input_hash, status, conversation_id, result_json, created_at, updated_at) "
                "VALUES (?, ?, 'hash1', 'completed', ?, ?, ?, ?)",
                ("req-1", "test-session", conv_id, result_json, db.now_iso(), db.now_iso()),
            )

        convs = db.recent_conversations(session_id="test-session")
        self.assertEqual(len(convs), 1)
        self.assertEqual(convs[0]["id"], conv_id)
        self.assertEqual(convs[0]["assistant_text"], "お疲れさまです")
        self.assertIn("model_route", convs[0])
        self.assertEqual(convs[0]["model_route"]["provider"], "antigravity_cli")
        self.assertEqual(convs[0]["model_route"]["model"], "gemini-3.8-flash-low")


if __name__ == "__main__":
    unittest.main()
