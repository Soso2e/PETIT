from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import config, lmstudio_client, model_routing


class _Response:
    def __init__(self, data: dict):
        self._data = data
        self.status_code = 200
        self.text = json.dumps(data)

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._data


class ModelRoutingTests(unittest.TestCase):
    def test_chat_and_agent_are_persisted_independently_without_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "routing.json"
            with patch.object(model_routing, "STATE_PATH", state_path), patch.dict(
                os.environ,
                {
                    "PETIT_DEEPSEEK_API_KEY": "super-secret",
                    "PETIT_CHAT_PROFILE": "local",
                    "PETIT_AGENT_PROFILE": "local",
                },
                clear=False,
            ):
                status = model_routing.update_selection({"chat": "deepseek_flash"})
                self.assertEqual(status["selections"], {"chat": "deepseek_flash", "agent": "local"})
                saved = state_path.read_text(encoding="utf-8")
                self.assertNotIn("super-secret", saved)
                self.assertEqual(json.loads(saved)["chat"], "deepseek_flash")

    def test_deepseek_cannot_be_selected_without_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(model_routing, "STATE_PATH", Path(tmp) / "routing.json"), patch.dict(
                os.environ,
                {"PETIT_DEEPSEEK_API_KEY": "", "DEEPSEEK_API_KEY": ""},
                clear=False,
            ):
                with self.assertRaises(model_routing.ModelRoutingError):
                    model_routing.update_selection({"agent": "deepseek_pro"})

    def test_public_status_never_exposes_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(model_routing, "STATE_PATH", Path(tmp) / "routing.json"), patch.dict(
                os.environ,
                {"PETIT_DEEPSEEK_API_KEY": "hidden-key"},
                clear=False,
            ):
                serialized = json.dumps(model_routing.public_status(), ensure_ascii=False)
                self.assertNotIn("hidden-key", serialized)
                self.assertNotIn("api_key", serialized)


class ProviderPayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        lmstudio_client.clear_health_cache()

    @patch("backend.lmstudio_client.httpx.post")
    @patch("backend.lmstudio_client.model_routing.endpoint")
    def test_deepseek_payload_uses_runtime_model_and_omits_lm_studio_fields(self, endpoint_mock, post_mock) -> None:
        endpoint_mock.return_value = {
            "route": "chat",
            "profile": "deepseek_flash",
            "label": "DeepSeek V4 Flash",
            "provider": "deepseek",
            "base_url": "https://api.deepseek.com",
            "api_key": "secret",
            "model": "deepseek-v4-flash",
            "configured": True,
            "external": True,
        }
        post_mock.return_value = _Response({"choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]})

        result = lmstudio_client.chat_completion(
            [{"role": "user", "content": "hello"}],
            model=config.CHAT_MODEL,
            route="chat",
        )

        self.assertEqual(result["content"], "ok")
        payload = post_mock.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "deepseek-v4-flash")
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertNotIn("chat_template_kwargs", payload)

    @patch("backend.lmstudio_client.httpx.post")
    @patch("backend.lmstudio_client.model_routing.endpoint")
    def test_local_payload_keeps_lm_studio_thinking_flag(self, endpoint_mock, post_mock) -> None:
        endpoint_mock.return_value = {
            "route": "agent",
            "profile": "local",
            "label": "ローカル LM Studio",
            "provider": "lm_studio",
            "base_url": "http://127.0.0.1:1234/v1",
            "api_key": "lm-studio",
            "model": "local-model",
            "configured": True,
            "external": False,
        }
        post_mock.return_value = _Response({"choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]})

        lmstudio_client.chat_completion([{"role": "user", "content": "hello"}], route="agent")
        payload = post_mock.call_args.kwargs["json"]
        self.assertIn("chat_template_kwargs", payload)
        self.assertNotIn("thinking", payload)


if __name__ == "__main__":
    unittest.main()
