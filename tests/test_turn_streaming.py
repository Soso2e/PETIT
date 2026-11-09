from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from backend import brain, config, conversation_api as api, conversation_store as store, db, lmstudio_client, tools, turn_stream


def _fake_sse_stream(lines: list[str], *, status_code: int = 200, text: str = ""):
    class FakeResp:
        def __init__(self):
            self.status_code = status_code
            self.text = text

        def read(self):
            return self.text.encode("utf-8")

        def raise_for_status(self):
            if self.status_code >= 400:
                req = httpx.Request("POST", "http://127.0.0.1:1234/v1/chat/completions")
                resp = httpx.Response(self.status_code, text=self.text, request=req)
                raise httpx.HTTPStatusError("err", request=req, response=resp)

        def iter_lines(self):
            return iter(lines)

    @contextmanager
    def cm(*_args, **_kwargs):
        yield FakeResp()

    return cm


class TurnStreamingTests(unittest.TestCase):
    def setUp(self):
        turn_stream.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for target, value in (
            ("DB_PATH", Path(self.temp.name) / "app.db"),
            ("notion_configured", lambda: False),
        ):
            p = patch.object(config, target, value)
            p.start()
            self.addCleanup(p.stop)
        p_env = patch.dict("os.environ", {"PETIT_SETTINGS_DIR": str(Path(self.temp.name) / "settings")})
        p_env.start()
        self.addCleanup(p_env.stop)
        from backend import setup_store as _settings
        _settings._sessions.clear()
        for target in ("backend.chroma_client.sync_structured_data", "backend.chroma_client.add",
                       "backend.chroma_client.delete_ids", "backend.chat._artifact_executor.submit"):
            p = patch(target)
            p.start()
            self.addCleanup(p.stop)
        db.init_db()
        store.ensure_schema()
        tools.register_builtin_tools()

    def test_turn_stream_lifecycle_and_reset(self):
        turn_stream.open("req-1")
        snap = turn_stream.snapshot("req-1")
        self.assertEqual(snap["phase"], "thinking")
        self.assertEqual(snap["text"], "")
        self.assertFalse(snap["closed"])

        turn_stream.delta("req-1", "おは")
        turn_stream.delta("req-1", "よう")
        snap = turn_stream.snapshot("req-1")
        self.assertEqual(snap["phase"], "replying")
        self.assertEqual(snap["text"], "おはよう")

        # Tool round or fallback discards draft text
        turn_stream.reset_text("req-1")
        turn_stream.phase("req-1", "tool", tool="get_tasks")
        snap = turn_stream.snapshot("req-1")
        self.assertEqual(snap["text"], "")
        self.assertEqual(snap["phase"], "tool")
        self.assertEqual(snap["tool"], "get_tasks")

        turn_stream.close("req-1", "completed")
        snap = turn_stream.snapshot("req-1")
        self.assertTrue(snap["closed"])
        self.assertEqual(snap["status"], "completed")

        # Updates after close are ignored
        turn_stream.delta("req-1", "ignored")
        self.assertEqual(turn_stream.snapshot("req-1")["text"], "")

    def test_lmstudio_client_stream_rebuilds_content_and_usage(self):
        sse_lines = [
            'data: {"choices":[{"index":0,"delta":{"role":"assistant","content":"こん"}}]}',
            'data: {"choices":[{"index":0,"delta":{"content":"にちは！"},"finish_reason":"stop"}]}',
            'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}',
            'data: [DONE]',
        ]
        deltas: list[str] = []
        target = {"provider": "lm_studio", "profile": "local", "label": "LM Studio",
                  "base_url": "http://127.0.0.1:1234/v1", "api_key": "lm-studio",
                  "model": "qwen", "configured": True}
        with patch.object(httpx, "stream", side_effect=_fake_sse_stream(sse_lines)), \
             lmstudio_client.observe_turn() as metrics:
            msg = lmstudio_client.chat_completion(
                [{"role": "user", "content": "挨拶して"}],
                target_override=target,
                on_delta=deltas.append,
            )
        self.assertEqual(deltas, ["こん", "にちは！"])
        self.assertEqual(msg["content"], "こんにちは！")
        self.assertEqual(msg["_finish_reason"], "stop")
        self.assertEqual(metrics["usage"][0]["total_tokens"], 15)

    def test_lmstudio_client_stream_accumulates_tool_calls(self):
        sse_lines = [
            'data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"id":"call_abc","function":{"name":"get_current_","arguments":"{\\"tz\\":"}}]}}]}',
            'data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"name":"time","arguments":"\\"UTC\\"}"}}]},"finish_reason":"tool_calls"}]}',
            'data: [DONE]',
        ]
        target = {"provider": "lm_studio", "profile": "local", "label": "LM Studio",
                  "base_url": "http://127.0.0.1:1234/v1", "api_key": "lm-studio",
                  "model": "qwen", "configured": True}
        with patch.object(httpx, "stream", side_effect=_fake_sse_stream(sse_lines)):
            msg = lmstudio_client.chat_completion(
                [{"role": "user", "content": "今何時？"}],
                target_override=target,
                on_delta=lambda _: None,
            )
        self.assertEqual(len(msg["tool_calls"]), 1)
        self.assertEqual(msg["tool_calls"][0]["id"], "call_abc")
        self.assertEqual(msg["tool_calls"][0]["function"]["name"], "get_current_time")
        self.assertEqual(msg["tool_calls"][0]["function"]["arguments"], '{"tz":"UTC"}')

    def test_lmstudio_client_stream_falls_back_when_endpoint_rejects_stream(self):
        target = {"provider": "lm_studio", "profile": "local", "label": "LM Studio",
                  "base_url": "http://127.0.0.1:1234/v1", "api_key": "lm-studio",
                  "model": "qwen", "configured": True}
        with patch.object(httpx, "stream", side_effect=_fake_sse_stream([], status_code=400)), \
             patch.object(lmstudio_client, "_post_completion", return_value={
                 "choices": [{"message": {"role": "assistant", "content": "非stream応答"}, "finish_reason": "stop"}]
             }) as fallback_post:
            msg = lmstudio_client.chat_completion(
                [{"role": "user", "content": "テスト"}],
                target_override=target,
                on_delta=lambda _: None,
            )
        self.assertEqual(msg["content"], "非stream応答")
        self.assertEqual(fallback_post.call_count, 1)

    def test_brain_discards_draft_on_tool_round_and_streams_final_round(self):
        observed_snapshots: list[dict] = []

        def fake_chat_completion(messages, tools=None, **kwargs):
            on_delta = kwargs.get("on_delta")
            if not any(m.get("role") == "tool" for m in messages):
                if on_delta:
                    on_delta("考え途中のドラフト")
                observed_snapshots.append(dict(turn_stream.snapshot("req-tool") or {}))
                return {
                    "role": "assistant",
                    "content": "考え途中のドラフト",
                    "tool_calls": [{"id": "c1", "type": "function",
                                    "function": {"name": "get_current_time", "arguments": "{}"}}],
                }
            # After tool call, draft must have been reset before final round
            observed_snapshots.append(dict(turn_stream.snapshot("req-tool") or {}))
            if on_delta:
                on_delta("最終")
                on_delta("回答だよ。")
            observed_snapshots.append(dict(turn_stream.snapshot("req-tool") or {}))
            return {"role": "assistant", "content": "最終回答だよ。"}

        target = {"provider": "lm_studio", "profile": "local", "label": "LM Studio",
                  "base_url": "http://127.0.0.1:1234/v1", "api_key": "lm-studio",
                  "model": "qwen", "configured": True}
        with patch.object(brain.lmstudio_client, "endpoint", return_value=target), \
             patch.object(brain.lmstudio_client, "chat_completion", side_effect=fake_chat_completion):
            result = api.submit("thread-1", "req-tool", "今何時？", is_admin=True)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["reply"], "最終回答だよ。")
        self.assertEqual(observed_snapshots[0]["text"], "考え途中のドラフト")
        # Reset occurred before round 2 started
        self.assertEqual(observed_snapshots[1]["text"], "")
        self.assertEqual(observed_snapshots[2]["text"], "最終回答だよ。")
        self.assertTrue(turn_stream.snapshot("req-tool")["closed"])

    def test_sse_endpoint_emits_progress_and_end_for_watched_turn(self):
        from backend.main import app
        from backend import setup_store

        setup_store.set_password("test-password-123")
        setup_store.update({"completed": True})
        token = setup_store.authenticate("test-password-123")

        turn_stream.open("req-sse")
        turn_stream.delta("req-sse", "テスト応答")
        turn_stream.close("req-sse", "completed")

        client = TestClient(app)
        client.cookies.set("petit_admin", token)
        resp = client.get("/api/turns/req-sse/stream")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers["content-type"].startswith("text/event-stream"))
        body = resp.text
        self.assertIn("event: progress", body)
        self.assertIn('"append": "テスト応答"', body)
        self.assertIn("event: end", body)
        self.assertIn('"status": "completed"', body)

    def test_frontend_contract_wires_progress_callback(self):
        root = Path(__file__).resolve().parents[1]
        session_js = (root / "frontend" / "session.js").read_text(encoding="utf-8")
        app_js = (root / "frontend" / "app.js").read_text(encoding="utf-8")
        universe_js = (root / "frontend" / "universe-app.js").read_text(encoding="utf-8")
        self.assertIn("/stream", session_js)
        self.assertIn("EventSource", session_js)
        self.assertIn("progress.text || progress.label", app_js)
        self.assertIn("progress.text || progress.label", universe_js)


if __name__ == "__main__":
    unittest.main()
