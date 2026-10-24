"""HTTP contract + real Core/Registry/SQLite, without external credentials."""
from __future__ import annotations

import copy
import importlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from backend import brain, conversation_api as api, conversation_store as store, db, lmstudio_client, model_routing
from tests import test_renaissance_core as core


def reply(content="返答", calls=None, usage=None):
    return {"choices": [{"message": {"role": "assistant", "content": content,
                                     **({"tool_calls": calls} if calls else {})}, "finish_reason": "stop"}],
            **({"usage": usage} if usage else {})}


class GeminiProviderTests(unittest.TestCase):
    def setUp(self):
        core.RenaissanceCoreTests.setUp(self)
        for p in (
            patch.dict(os.environ, {"PETIT_CHAT_PROFILE": "gemini", "PETIT_GEMINI_API_KEY": "gemini-secret",
                                    "PETIT_DEEPSEEK_API_KEY": "deepseek-secret", "PETIT_DEEPSEEK_FALLBACK_THREADS": "a"}),
            patch.object(model_routing, "STATE_PATH", Path(self.temp.name) / "models.json"),
        ):
            p.start()
            self.addCleanup(p.stop)
        self.sent = []

    def submit(self, outputs, *, request_id="r", thread="a", message="相談"):
        outputs = iter(outputs)
        def post(url, **kwargs):
            self.sent.append((url, {**kwargs, "json": copy.deepcopy(kwargs["json"])}))
            output = next(outputs)
            if isinstance(output, Exception):
                raise output
            status, data = output if isinstance(output, tuple) else (200, output)
            return httpx.Response(status, json=data, request=httpx.Request("POST", url))
        with patch.object(lmstudio_client.httpx, "post", side_effect=post):
            return api.submit(thread, request_id, message)

    def test_gemini_profile_is_explicit_and_never_exposes_key(self):
        status = model_routing.update_selection({"chat": "gemini"})
        self.assertEqual(status["routes"]["chat"]["active"]["label"], "Gemini API")
        self.assertNotIn("gemini-secret", json.dumps(status))
        self.assertNotIn("secret", model_routing.STATE_PATH.read_text())
        with patch.dict(os.environ, {"PETIT_GEMINI_API_KEY": "", "GEMINI_API_KEY": ""}):
            with self.assertRaises(model_routing.ModelRoutingError):
                model_routing.update_selection({"chat": "gemini"})
            result = self.submit([])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.sent, [])

    def test_standard_gemini_key_is_used_when_petit_override_is_empty(self):
        with patch.dict(os.environ, {"PETIT_GEMINI_API_KEY": "", "GEMINI_API_KEY": "standard-secret"}):
            self.assertTrue(model_routing.endpoint("chat")["configured"])
            self.assertEqual(model_routing.endpoint("chat")["api_key"], "standard-secret")

    def test_chat_uses_official_endpoint_native_payload_and_unknown_quota(self):
        result = self.submit([reply("こんにちは", usage={"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17})])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(self.sent), 1)
        url, kwargs = self.sent[0]
        self.assertEqual(url, "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")
        payload = kwargs["json"]
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer gemini-secret")
        self.assertEqual(payload["model"], "gemini-3.8-flash")
        self.assertEqual(payload["tool_choice"], "auto")
        self.assertNotIn("thinking", payload)
        self.assertNotIn("chat_template_kwargs", payload)
        self.assertEqual(result["used_tools"], [])
        self.assertEqual(result["model_route"]["quota"], "unknown")
        self.assertEqual(result["model_route"]["usage"]["total_tokens"], 17)
        self.assertNotIn("secret", json.dumps(result))

    def test_multiple_tools_native_signatures_and_next_turn_history(self):
        call = core.call("get_current_time")
        call["extra_content"] = {"google": {"thought_signature": "opaque-signature"}}
        result = self.submit([reply("", [call]), reply("", [core.call("get_work_status", call_id="two")]), reply("確認したよ")])
        self.assertEqual(result["status"], "completed")
        assistant = next(m for m in self.sent[1][1]["json"]["messages"] if m["role"] == "assistant")
        self.assertEqual(assistant["tool_calls"][0]["extra_content"], call["extra_content"])
        self.assertEqual({m["tool_call_id"] for m in self.sent[2][1]["json"]["messages"] if m["role"] == "tool"}, {"call-1", "two"})
        self.submit([reply("続き")], request_id="next", message="もう少し教えて")
        history = self.sent[-1][1]["json"]["messages"]
        self.assertIn("確認したよ", [m.get("content") for m in history])
        self.assertEqual(result["model_route"]["llm_call_count"], 3)

    def test_transient_errors_fallback_once_and_replay_never_calls_provider(self):
        for i, failure in enumerate([(429, {}), (503, {}), httpx.ReadTimeout("private detail"), httpx.ConnectError("secret")]):
            result = self.submit([failure, reply("代替から返答")], request_id=f"r{i}")
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["model_route"]["provider"], "deepseek")
            self.assertEqual(len(result["model_route"]["fallback"]), 1)
            self.assertEqual(len(result["model_route"]["attempts"]), 2)
            self.assertEqual(result["model_route"]["usage"], "unknown")
            self.assertEqual(self.sent[-1][1]["json"]["thinking"], {"type": "disabled"})
            self.assertNotIn("reasoning_effort", self.sent[-1][1]["json"])
            with patch.object(lmstudio_client.httpx, "post", side_effect=AssertionError("duplicate request")):
                self.assertEqual(api.submit("a", f"r{i}", "相談")["reply"], result["reply"])

    def test_auth_permission_and_bad_requests_do_not_fallback_or_echo_bodies(self):
        for code in (400, 401, 402, 403):
            result = self.submit([(code, {"error": "gemini-secret private input"})], request_id=f"r{code}")
            self.assertEqual(result["status"], "failed")
            self.assertEqual(len(result["model_route"]["attempts"]), 1)
            self.assertEqual(result["model_route"]["fallback"], [])
            self.assertNotIn("gemini-secret", json.dumps(result))

    def test_consent_is_per_thread_and_local_only_never_sends(self):
        result = self.submit([(429, {})], thread="unconsented")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(self.sent), 1)
        store.create_thread("private", privacy="local_only")
        result = self.submit([], thread="private", request_id="private")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(self.sent), 1)
        with patch.dict(os.environ, {"PETIT_CHAT_PROFILE": "local"}):
            result = self.submit([(503, {})], request_id="local")
        self.assertEqual(result["model_route"]["provider"], "lm_studio")
        self.assertEqual(len(result["model_route"]["attempts"]), 1)

    def test_no_fallback_after_read_tool_or_local_write(self):
        for i, call in enumerate([core.call("get_current_time"), core.call("save_memory", {"content": "合成メモ"})]):
            result = self.submit([reply("", [call]), (503, {})], request_id=f"r{i}")
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["model_route"]["fallback"], [])
            self.assertTrue(all(a["provider"] == "gemini" for a in result["model_route"]["attempts"]))
        self.assertEqual(result["effects"][0]["status"], "applied")

    def test_no_fallback_after_unknown_external_effect(self):
        store.create_thread("a")
        store.accept("a", "r", {"message": "相談"})
        store.begin_effect("r", core.call("add_schedule"), {})
        with patch.object(lmstudio_client.httpx, "post", return_value=httpx.Response(
                503, request=httpx.Request("POST", "https://example.test"))):
            result = api.process("r")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["model_route"]["fallback"], [])

    def test_approval_resume_restores_fallback_pin_and_receipt_once(self):
        args = {"title": "合成予定", "start_time": "2026-11-02T10:00:00+09:00"}
        result = self.submit([(429, {}), reply("", [core.call("add_schedule", args)])])
        self.assertEqual(result["status"], "waiting_approval")
        approval_id = result["pending_actions"][0]["approval_id"]
        importlib.reload(store)
        with patch.object(lmstudio_client.httpx, "post", return_value=httpx.Response(
                200, json=reply("登録結果を確認したよ"), request=httpx.Request("POST", "https://example.test"))) as post:
            decided = api.decide(approval_id, True)
            replay = api.decide(approval_id, True)
        self.assertEqual(decided["status"], "completed")
        self.assertEqual(decided["model_route"]["provider"], "deepseek")
        self.assertEqual(decided["effects"][0]["status"], "applied")
        self.assertEqual(replay["reply"], decided["reply"])
        self.assertEqual(post.call_count, 1)
        self.assertEqual(len(decided["model_route"]["attempts"]), 3)

    def test_consent_revocation_blocks_resumed_model_without_replaying_write(self):
        args = {"title": "合成予定", "start_time": "2026-11-02T10:00:00+09:00"}
        result = self.submit([(429, {}), reply("", [core.call("add_schedule", args)])])
        with patch.dict(os.environ, {"PETIT_DEEPSEEK_FALLBACK_THREADS": ""}), patch.object(lmstudio_client.httpx, "post") as post:
            decided = api.decide(result["pending_actions"][0]["approval_id"], False)
        self.assertEqual(decided["status"], "failed")
        post.assert_not_called()

    def test_empty_or_malformed_output_fails_without_context_truncation(self):
        for i, output in enumerate([reply(""), {"unexpected": "private input"}]):
            result = self.submit([output], request_id=f"r{i}")
            self.assertEqual(result["status"], "failed")
            self.assertEqual(len(result["model_route"]["attempts"]), 1)
            self.assertEqual(result["model_route"]["fallback"], [])

    def test_http_chat_and_saved_turn_report_actual_provider(self):
        from backend import lifecycle
        from backend.app import create_app
        with patch.object(lifecycle, "startup", store.recover), patch.object(lifecycle, "shutdown"), TestClient(create_app()) as client:
            status = client.get("/api/model-routing").json()
            self.assertEqual(status["routes"]["chat"]["active"]["provider"], "gemini")
            with patch.object(lmstudio_client.httpx, "post", return_value=httpx.Response(
                    200, json=reply("HTTPから返答"), request=httpx.Request("POST", "https://example.test"))):
                result = client.post("/api/chat", json={"message": "相談", "request_id": "http", "session_id": "a"}).json()
            self.assertEqual(result["model_route"]["provider"], "gemini")
            saved = client.get("/api/turns/http").json()
            self.assertEqual(saved["model_route"], result["model_route"])
            self.assertNotIn("gemini-secret", json.dumps(saved))

    def test_approved_external_write_is_not_repeated_after_model_timeout(self):
        args = {"title": "合成予定", "start_time": "2026-11-02T10:00:00+09:00"}
        result = self.submit([reply("", [core.call("add_schedule", args)])])
        with patch.object(lmstudio_client.httpx, "post", side_effect=httpx.ReadTimeout("timeout")) as post:
            decided = api.decide(result["pending_actions"][0]["approval_id"], True)
            replay = api.decide(result["pending_actions"][0]["approval_id"], True)
        self.assertEqual(decided["status"], "failed")
        self.assertEqual(decided["effects"][0]["status"], "applied")
        self.assertEqual(decided["model_route"]["fallback"], [])
        self.assertEqual(post.call_count, 1)
        self.assertEqual(replay["effects"], decided["effects"])

    def test_changing_primary_before_resume_blocks_context_egress(self):
        result = self.submit([reply("", [core.call("add_schedule", {"title": "予定", "start_time": "2026-11-02T10:00:00+09:00"})])])
        with patch.dict(os.environ, {"PETIT_GEMINI_MODEL": "different-model"}), patch.object(lmstudio_client.httpx, "post") as post:
            decided = api.decide(result["pending_actions"][0]["approval_id"], False)
        self.assertEqual(decided["status"], "failed")
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
