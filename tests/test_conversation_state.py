from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import config, conversation_state, db


class ConversationStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(config, "DB_PATH", Path(self.temp_dir.name) / "app.db")
        self.db_patch.start()
        db.init_db()

    def tearDown(self) -> None:
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_state_is_saved_per_session_without_llm(self) -> None:
        with patch.object(conversation_state, "_active_project", return_value={"id": "p1", "name": "PETIT", "status": "active"}):
            state = conversation_state.update_after_turn(
                "session-a",
                user_text="PETITはContext Broker方式で進めることにする",
                assistant_text="了解。次はConversation Stateを入れる。",
            )

        self.assertIsNotNone(state)
        self.assertEqual(state["active_project"]["name"], "PETIT")
        self.assertIn("PETIT", state["recent_entities"])
        self.assertTrue(state["recent_decisions"])
        self.assertEqual(state["current_topic"], "PETITはContext Broker方式で進めることにする")

    def test_continuation_keeps_previous_topic_and_goal(self) -> None:
        conversation_state.update_after_turn(
            "session-a",
            user_text="Conversation Stateの設計を詰めたい",
            assistant_text="まず保存項目を決めよう。",
        )
        state = conversation_state.update_after_turn(
            "session-a",
            user_text="その続きやろう",
            assistant_text="保存項目の続きから進める。",
        )

        self.assertEqual(state["current_topic"], "Conversation Stateの設計を詰めたい")
        self.assertEqual(state["user_goal"], "Conversation Stateの設計を詰めたい")
        self.assertEqual(state["last_user_text"], "その続きやろう")

    def test_state_is_isolated_by_session(self) -> None:
        conversation_state.update_after_turn("a", user_text="卒研の話", assistant_text="了解")
        conversation_state.update_after_turn("b", user_text="PETITの話", assistant_text="了解")

        self.assertEqual(conversation_state.load("a")["current_topic"], "卒研の話")
        self.assertEqual(conversation_state.load("b")["current_topic"], "PETITの話")

    def test_render_is_bounded(self) -> None:
        state = {
            "current_topic": "x" * 1000,
            "user_goal": "y" * 1000,
            "recent_decisions": ["d" * 300] * 5,
            "unresolved_items": ["u" * 300] * 5,
            "recent_entities": ["entity"] * 5,
            "last_user_text": "z" * 1000,
        }
        rendered = conversation_state.render_for_model(state, max_chars=500)
        self.assertLessEqual(len(rendered), 500)

    def test_missing_session_disables_state(self) -> None:
        self.assertIsNone(conversation_state.load(None))
        self.assertIsNone(
            conversation_state.update_after_turn(None, user_text="test", assistant_text="reply")
        )


if __name__ == "__main__":
    unittest.main()
