import unittest
from unittest.mock import patch
from pydantic import ValidationError
from backend import chat, request_context, brain_runtime, capability_router
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
        def run(message, history):
            seen.append((message, request_context.current_conversation_mode()))
            raise RuntimeError('fixture stops before persistence')
        with patch.object(chat.agent, 'run', side_effect=run), patch.object(chat.log, 'exception'):
            response = chat.chat(chat.ChatRequest(message='続きやろう', conversation_mode='voice'))
        self.assertIsNotNone(response.error)
        self.assertEqual(seen, [('続きやろう', 'voice')])
        self.assertEqual(request_context.current_conversation_mode(), 'text')

    def test_broker_and_deep_messages_preserve_user_and_history(self):
        history = [{'role': 'user', 'content': '制作してる'}]
        with request_context.bind(request_id=None, session_id=None, conversation_mode='voice'):
            messages = brain_runtime._base_messages(history, '続きやろう', '')
        self.assertIn('1〜3文', messages[0]['content'])
        self.assertEqual(messages[1], history[0])
        self.assertEqual(messages[-1]['content'], '続きやろう')
        self.assertNotIn('1〜3文', brain_runtime._base_messages(history, '続きやろう', '')[0]['content'])

    def test_one_pass_brain_receives_voice_instructions(self):
        with request_context.bind(request_id=None, session_id=None, conversation_mode='voice'), \
             patch.object(capability_router.situation, 'build_active_work_context', return_value=''), \
             patch.object(capability_router.workspace_context, 'build_context_block', return_value=''), \
             patch.object(capability_router, 'chat_completion', return_value={'content': 'こんにちは。'}) as completion:
            result = capability_router.choose('こんにちは', [])
        self.assertIn('1〜3文', completion.call_args.args[0][0]['content'])
        self.assertEqual(result['reply'], 'こんにちは。')


if __name__ == '__main__':
    unittest.main()
