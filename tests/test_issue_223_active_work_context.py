from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import capability_router, config, proactive, situation, work_sessions


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

    def test_general_question_receives_active_context_without_forced_tool_route(self) -> None:
        captured: dict[str, object] = {}

        def fake_chat(messages, **kwargs):
            captured["messages"] = messages
            captured["tools"] = kwargs.get("tools")
            return {"content": "値上げの確認には最新情報が必要だね。"}

        session = {
            "task": "卒研報告書",
            "status": "active",
            "elapsed_seconds": 600,
        }
        with (
            patch.object(situation.work_sessions, "active_session", return_value=session),
            patch.object(capability_router, "chat_completion", side_effect=fake_chat),
        ):
            result = capability_router.choose("一般的な考え方を教えて")

        self.assertEqual(result["type"], "reply")
        self.assertEqual(result["source"], "one_pass_reply")
        user_message = captured["messages"][-1]["content"]
        self.assertIn("【現在の作業】", user_message)
        self.assertIn("卒研報告書", user_message)
        self.assertIsNotNone(captured["tools"])

    def test_general_question_does_not_end_active_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "petit.db"
            with patch.object(config, "DB_PATH", db_path):
                work_sessions.start_session("session-223", "卒研報告書")
                with patch.object(
                    capability_router,
                    "chat_completion",
                    return_value={"content": "一般的な回答だよ。"},
                ):
                    result = capability_router.choose("考え方を教えて")

                self.assertEqual(result["type"], "reply")
                active = work_sessions.active_session()
                self.assertIsNotNone(active)
                self.assertEqual(active["session_id"], "session-223")
                self.assertEqual(active["status"], "active")

    def test_agent_goal_keeps_active_context_without_adding_work_capability(self) -> None:
        response = {
            "tool_calls": [
                {
                    "function": {
                        "name": "route_to_agent",
                        "arguments": json.dumps(
                            {
                                "capabilities": ["web"],
                                "goal": "DeepSeekの現在価格を確認する",
                            },
                            ensure_ascii=False,
                        ),
                    }
                }
            ]
        }
        session = {"task": "卒研報告書", "status": "active", "elapsed_seconds": 600}
        with (
            patch.object(situation.work_sessions, "active_session", return_value=session),
            patch.object(capability_router, "chat_completion", return_value=response),
        ):
            result = capability_router.choose("DeepSeek値上げした？")

        self.assertEqual(result["capabilities"], ["web"])
        self.assertIn("卒研報告書", result["goal"])

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


if __name__ == "__main__":
    unittest.main()
