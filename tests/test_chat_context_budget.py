from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

from backend import config, lmstudio_client


class EmptyModelResponseRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.endpoint_patch = patch.object(
            lmstudio_client,
            "endpoint",
            side_effect=lambda route: {
                "configured": True,
                "provider": "lm_studio",
                "label": "LM Studio",
                "base_url": "http://localhost:1234/v1",
                "api_key": "lm-studio",
                "model": "local-model",
                "profile": "local",
            },
        )
        self.endpoint_patch.start()

    def tearDown(self) -> None:
        self.endpoint_patch.stop()

    @staticmethod
    def _response(content: str, *, finish_reason: str = "stop") -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": finish_reason,
                    }
                ]
            },
            request=httpx.Request("POST", "http://localhost:1234/v1/chat/completions"),
        )

    def test_empty_content_retries_with_compact_context(self) -> None:
        responses = [self._response(""), self._response("復旧しました。")]
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "前の質問"},
            {"role": "assistant", "content": "前の回答"},
            {"role": "user", "content": "Linkraftって知ってる？"},
        ]

        with patch.object(lmstudio_client.httpx, "post", side_effect=responses) as post:
            result = lmstudio_client.chat_completion(messages, route="chat")

        self.assertEqual(result["content"], "復旧しました。")
        self.assertTrue(result["_empty_response_recovered"])
        self.assertEqual(post.call_count, 2)
        retry_payload = post.call_args_list[1].kwargs["json"]
        self.assertEqual(
            retry_payload["messages"],
            [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "Linkraftって知ってる？"},
            ],
        )
        self.assertEqual(retry_payload["temperature"], 0)
        self.assertEqual(retry_payload["chat_template_kwargs"], {"enable_thinking": False})

    def test_two_empty_responses_return_stable_fallback(self) -> None:
        responses = [self._response(""), self._response("")]
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "Linkraft"},
        ]

        with patch.object(lmstudio_client.httpx, "post", side_effect=responses) as post:
            result = lmstudio_client.chat_completion(messages, route="chat")

        self.assertEqual(result["content"], lmstudio_client._EMPTY_REPLY_FALLBACK)
        self.assertEqual(result["_finish_reason"], "empty_response_fallback")
        self.assertEqual(post.call_count, 2)


if __name__ == "__main__":
    unittest.main()
