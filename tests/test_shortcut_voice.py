from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from backend import main, shortcut_voice


class ShortcutVoiceApiTests(unittest.TestCase):
    def test_api_route_is_registered(self) -> None:
        paths = {getattr(route, "path", None) for route in main.app.routes}
        self.assertIn("/api/voice", paths)

    def test_voice_shortcut_reuses_normal_chat_path(self) -> None:
        chat_response = main.ChatResponse(
            reply="今日はPETITの確認から始めよう。",
            request_id="req-test",
        )
        with patch.object(main, "chat", return_value=chat_response) as chat:
            result = shortcut_voice.voice_shortcut(
                shortcut_voice.VoiceShortcutRequest(
                    message="  今日なにする？  ",
                    session_id="iphone-1",
                )
            )

        sent = chat.call_args.args[0]
        self.assertEqual(sent.message, "今日なにする？")
        self.assertEqual(sent.session_id, "iphone-1")
        self.assertTrue(str(sent.request_id).startswith("ios_"))
        self.assertTrue(result.ok)
        self.assertEqual(result.reply, "今日はPETITの確認から始めよう。")
        self.assertEqual(result.source, "ios_shortcut")
        self.assertEqual(result.request_id, "req-test")
        self.assertFalse(result.needs_confirmation)

    def test_default_session_and_pending_confirmation_are_preserved(self) -> None:
        chat_response = main.ChatResponse(
            reply="確認してから実行するよ。",
            request_id="req-confirm",
            pending_actions=[
                main.PendingAction(
                    approval_id="approval-1",
                    name="complete_task",
                    arguments={"task_id": 12},
                )
            ],
        )
        with patch.object(main, "chat", return_value=chat_response) as chat:
            result = shortcut_voice.voice_shortcut(
                shortcut_voice.VoiceShortcutRequest(message="このタスク終わった")
            )

        sent = chat.call_args.args[0]
        self.assertEqual(sent.session_id, shortcut_voice.DEFAULT_SESSION_ID)
        self.assertTrue(result.ok)
        self.assertTrue(result.needs_confirmation)
        self.assertEqual(len(result.pending_actions), 1)
        self.assertEqual(result.pending_actions[0]["name"], "complete_task")
        self.assertEqual(result.pending_actions[0]["arguments"], {"task_id": 12})

    def test_blank_message_is_rejected(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            shortcut_voice.voice_shortcut(
                shortcut_voice.VoiceShortcutRequest(message="   ")
            )
        self.assertEqual(raised.exception.status_code, 400)

    def test_overlong_message_is_rejected_by_schema(self) -> None:
        with self.assertRaises(ValidationError):
            shortcut_voice.VoiceShortcutRequest(
                message="x" * (shortcut_voice.MAX_MESSAGE_CHARS + 1)
            )

    def test_chat_error_is_returned_without_hiding_it(self) -> None:
        chat_response = main.ChatResponse(
            reply="",
            error="LM Studioへ接続できません。",
            request_id="req-error",
        )
        with patch.object(main, "chat", return_value=chat_response):
            result = shortcut_voice.voice_shortcut(
                shortcut_voice.VoiceShortcutRequest(message="こんにちは")
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.reply, "")
        self.assertEqual(result.error, "LM Studioへ接続できません。")
        self.assertEqual(result.request_id, "req-error")


if __name__ == "__main__":
    unittest.main()
