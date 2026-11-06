import unittest
from unittest.mock import patch
from pydantic import ValidationError
from backend import chat, request_context, brain, config, db
import tempfile
from pathlib import Path
from backend.petit_prompt import voice_turn_instructions


class VoiceConversationModeTests(unittest.TestCase):
    def test_api_default_and_validation(self):
        self.assertEqual(chat.ChatRequest(message='こんにちは').conversation_mode, 'text')
        with self.assertRaises(ValidationError):
            chat.ChatRequest(message='こんにちは', conversation_mode='invalid')

    def test_context_restored_on_error_and_nested_request(self):
        self.assertEqual(voice_turn_instructions(), '')
        with request_context.bind(request_id='voice', session_id='session', conversation_mode='voice'):
            self.assertIn('1〜3文', voice_turn_instructions())
            with self.assertRaises(RuntimeError):
                with request_context.bind(request_id='text', session_id='session'):
                    self.assertEqual(voice_turn_instructions(), '')
                    raise RuntimeError('offline')
            self.assertEqual(request_context.current_ids(), ('voice', 'session'))
            self.assertIn('1〜3文', voice_turn_instructions())
        self.assertEqual(voice_turn_instructions(), '')

    def test_chat_binds_mode_without_changing_message(self):
        seen = []
        def run(messages, **kwargs):
            seen.append((messages[-1]["content"], request_context.current_conversation_mode()))
            raise RuntimeError('fixture stops before persistence')
        with tempfile.TemporaryDirectory() as directory, patch.object(config, "DB_PATH", Path(directory) / "app.db"), \
             patch.object(brain.lmstudio_client, 'chat_completion', side_effect=run):
            db.init_db()
            response = chat.chat(chat.ChatRequest(message='続きやろう', conversation_mode='voice'))
        self.assertIsNotNone(response.error)
        self.assertEqual(seen, [('続きやろう', 'voice')])
        self.assertEqual(request_context.current_conversation_mode(), 'text')




if __name__ == '__main__':
    unittest.main()
