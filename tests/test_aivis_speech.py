from __future__ import annotations

import ast
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from backend import aivis_speech, config


class FakeResponse:
    def __init__(self, *, json_data=None, content: bytes = b"", status_code: int = 200) -> None:
        self._json_data = json_data
        self.content = content
        self.status_code = status_code
        self.request = httpx.Request("GET", "http://test")

    def json(self):
        return self._json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "failed",
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request),
            )


class FakeClient:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def _next(self) -> FakeResponse:
        return self.responses.pop(0)

    def get(self, url: str, **kwargs) -> FakeResponse:
        self.calls.append(("GET", url, kwargs))
        return self._next()

    def post(self, url: str, **kwargs) -> FakeResponse:
        self.calls.append(("POST", url, kwargs))
        return self._next()


class AivisSpeechTests(unittest.TestCase):
    def _config_patches(self, **overrides):
        values = {
            "TTS_PROVIDER": "aivis",
            "TTS_BASE_URL": "http://127.0.0.1:10101",
            "TTS_STYLE_ID": 123,
            "TTS_TIMEOUT": 10.0,
            "TTS_MAX_CHARS": 1000,
            "TTS_SPEED_SCALE": 1.15,
            "TTS_INTONATION_SCALE": 0.9,
            "TTS_VOLUME_SCALE": 1.1,
        }
        values.update(overrides)
        return [patch.object(config, name, value) for name, value in values.items()]

    def test_synthesize_uses_configured_style_and_adjusts_query(self) -> None:
        client = FakeClient([
            FakeResponse(json_data={"speedScale": 1.0, "intonationScale": 1.0, "volumeScale": 1.0}),
            FakeResponse(content=b"RIFF-audio"),
        ])
        patches = self._config_patches()
        for item in patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(patches)])

        with patch.object(aivis_speech.httpx, "Client", return_value=client):
            audio, style_id = aivis_speech.synthesize("こんにちは")

        self.assertEqual(audio, b"RIFF-audio")
        self.assertEqual(style_id, 123)
        self.assertEqual([call[0] for call in client.calls], ["POST", "POST"])
        self.assertEqual(client.calls[0][2]["params"], {"text": "こんにちは", "speaker": 123})
        synthesis_query = client.calls[1][2]["json"]
        self.assertEqual(synthesis_query["speedScale"], 1.15)
        self.assertEqual(synthesis_query["intonationScale"], 0.9)
        self.assertEqual(synthesis_query["volumeScale"], 1.1)

    def test_synthesize_auto_selects_first_available_style(self) -> None:
        client = FakeClient([
            FakeResponse(json_data=[{"name": "PETIT", "styles": [{"id": 888, "name": "通常"}]}]),
            FakeResponse(json_data={}),
            FakeResponse(content=b"RIFF"),
        ])
        patches = self._config_patches(TTS_STYLE_ID=None)
        for item in patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(patches)])

        with patch.object(aivis_speech.httpx, "Client", return_value=client):
            _audio, style_id = aivis_speech.synthesize("テスト")

        self.assertEqual(style_id, 888)
        self.assertEqual(client.calls[0][0], "GET")
        self.assertTrue(client.calls[0][1].endswith("/speakers"))

    def test_synthesize_rejects_too_long_text(self) -> None:
        patches = self._config_patches(TTS_MAX_CHARS=3)
        for item in patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(patches)])

        with self.assertRaisesRegex(aivis_speech.AivisSpeechError, "3文字以内"):
            aivis_speech.synthesize("1234")

    def test_status_reports_unavailable_engine_without_raising(self) -> None:
        patches = self._config_patches()
        for item in patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(patches)])

        with patch.object(aivis_speech.httpx, "Client", side_effect=httpx.ConnectError("offline")):
            result = aivis_speech.status(check_engine=True)

        self.assertFalse(result["available"])
        self.assertIn("offline", result["error"])

    def test_main_declares_tts_routes(self) -> None:
        source = Path("backend/main.py").read_text(encoding="utf-8")
        ast.parse(source)
        self.assertIn('@app.post("/api/tts")', source)
        self.assertIn('@app.get("/api/tts/status")', source)


if __name__ == "__main__":
    unittest.main()
