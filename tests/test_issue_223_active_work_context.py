from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import config, proactive, situation, work_sessions


class Issue223ActiveWorkContextTests(unittest.TestCase):
    def test_no_session_adds_no_context(self) -> None:
        with patch.object(situation.work_sessions, "active_session", return_value=None):
            self.assertEqual(situation.build_active_work_context(), "")

    def test_context_failure_does_not_break_conversation_entry(self) -> None:
        with patch.object(
            situation.work_sessions,
            "active_session",
            side_effect=RuntimeError("database unavailable"),
        ):
            self.assertEqual(situation.build_active_work_context(), "")

    def test_paused_session_is_compact_and_not_described_as_active(self) -> None:
        session = {
            "task": "卒研報告書",
            "task_id": "task-1",
            "project_id": "graduation",
            "status": "paused",
            "elapsed_seconds": 1620,
        }
        with patch.object(situation.work_sessions, "active_session", return_value=session):
            context = situation.build_active_work_context()

        self.assertIn("task: 卒研報告書", context)
        self.assertIn("status: paused", context)
        self.assertIn("elapsed_minutes: 27", context)
        self.assertIn("現在は休憩中", context)




    def test_proactive_opener_prefers_real_session_over_stale_project_memory(self) -> None:
        session = {"task": "卒研報告書", "status": "active"}
        with (
            patch.object(proactive, "_time_of_day", return_value="夜"),
            patch.object(proactive.db, "recent_episodes", return_value=[]),
            patch.object(proactive.db, "recent_summaries", return_value=[]),
            patch.object(proactive.db, "all_memory", return_value=[{"type": "project", "content": "古い作業"}]),
            patch.object(proactive.work_sessions, "active_session", return_value=session),
            patch.object(proactive, "chat_completion", side_effect=proactive.LMStudioError("offline")),
        ):
            result = proactive.generate_opener()

        self.assertEqual(result["kind"], "template")
        self.assertIn("卒研報告書", result["message"])
        self.assertNotIn("古い作業", result["message"])

    def test_proactive_opener_does_not_use_global_episode_as_current_fact(self) -> None:
        captured: dict[str, object] = {}

        def fake_chat(messages, **kwargs):
            captured["messages"] = messages
            return {"content": "続き、どうする？"}

        with (
            patch.object(proactive, "_time_of_day", return_value="昼"),
            patch.object(proactive.db, "recent_episodes", return_value=[{"summary": "全タスクをキャンセル済み"}]),
            patch.object(proactive.db, "recent_summaries", return_value=[{"summary": "古い要約"}]),
            patch.object(proactive.db, "recent_conversations", return_value=[]),
            patch.object(proactive.db, "all_memory", return_value=[]),
            patch.object(proactive.work_sessions, "active_session", return_value=None),
            patch.object(proactive, "chat_completion", side_effect=fake_chat),
        ):
            result = proactive.generate_opener(session_id="new-session")

        self.assertEqual(result["kind"], "llm")
        prompt = captured["messages"][-1]["content"]
        self.assertNotIn("キャンセル済み", prompt)
        self.assertNotIn("古い要約", prompt)


if __name__ == "__main__":
    unittest.main()
