from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import ModuleType
import unittest
from unittest.mock import patch

from backend import antigravity_brain as sdk, brain, config, conversation_api as api
from backend import conversation_store as store, db, model_routing, tools


class SDKCoreContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for name, value in (("DB_PATH", Path(self.temp.name) / "app.db"),
                            ("notion_configured", lambda: False), ("USE_SONA_CORE", False)):
            context = patch.object(config, name, value)
            context.start(); self.addCleanup(context.stop)
        for name in ("backend.chroma_client.sync_structured_data", "backend.chroma_client.add",
                     "backend.chroma_client.delete_ids", "backend.chat._artifact_executor.submit"):
            context = patch(name)
            context.start(); self.addCleanup(context.stop)
        db.init_db(); store.ensure_schema(); tools.register_builtin_tools()
        self.target = {"provider": "antigravity_sdk", "profile": "antigravity_sdk", "model": "synthetic",
                       "auth_mode": "local", "base_url": "http://127.0.0.1:1234/v1", "configured": True,
                       "external": False, "timeout_seconds": 1}
        context = patch.object(brain.lmstudio_client, "endpoint", side_effect=lambda route: dict(self.target))
        context.start(); self.addCleanup(context.stop)

    def accepted(self):
        store.create_thread("sdk-thread")
        store.accept("sdk-thread", "sdk-request", {"message": "合成データ"})
        store.claim("sdk-request")

    def test_sdk_owns_loop_and_read_dispatch_and_replay_are_core_owned(self):
        def runtime(request_id, target, instructions, prompt, used, metadata):
            self.assertNotIn('"name": "create_task"', instructions)
            raw = sdk.bridge(request_id, target, used)("get_tasks", "{}")
            self.assertIsInstance(raw, str)
            metadata["sdk_conversation_id"] = "synthetic-session"
            return "SDKからの返答"
        with patch.object(sdk, "run_isolated", side_effect=runtime) as runtime_mock, \
             patch.object(brain.lmstudio_client, "chat_completion", side_effect=AssertionError("double loop")):
            result = api.submit("sdk-thread", "sdk-request", "合成データ")
            replay = api.submit("sdk-thread", "sdk-request", "合成データ")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["used_tools"][0]["name"], "get_tasks")
        self.assertEqual(result["model_route"]["provider"], "antigravity_sdk")
        self.assertEqual(replay["reply"], result["reply"])
        self.assertEqual(runtime_mock.call_count, 1)
        self.assertEqual(result["effects"], [])
        self.assertEqual(store.snapshot("sdk-thread")["events"][-2]["type"], "model_backend")

    def test_bridge_rechecks_risk_and_rejects_all_writes_and_bad_arguments(self):
        self.accepted()
        read = sdk.bridge("sdk-request", self.target, [])
        for name, args in (("create_task", '{"title":"must not create"}'), ("run_command", "{}"),
                           ("get_tasks", '{"invented":true}'), ("get_tasks", "[]"),
                           ("get_tasks", '{"x":NaN}')):
            with self.subTest(name=name, args=args), patch.object(brain, "execute") as execute:
                with self.assertRaises(ValueError):
                    read(name, args)
                execute.assert_not_called()
        from backend.tools import registry
        with patch.object(registry._REGISTRY["get_tasks"], "risk", "confirm_write"), self.assertRaises(ValueError):
            read("get_tasks", "{}")

    def test_provider_change_and_cancel_prevent_a_read(self):
        self.accepted()
        read = sdk.bridge("sdk-request", dict(self.target), [])
        self.target["model"] = "other"
        with self.assertRaises(ValueError):
            read("get_tasks", "{}")
        with db.get_connection() as connection:
            connection.execute("UPDATE turns SET cancel_requested=1 WHERE request_id='sdk-request'")
        with self.assertRaises(brain.TurnCancelled):
            read("get_tasks", "{}")

    def test_local_only_allows_loopback_sdk_and_blocks_cloud(self):
        store.create_thread("private", privacy="local_only")
        def runtime(*args):
            return "ローカル返答"
        with patch.object(sdk, "run_isolated", side_effect=runtime) as runtime_mock:
            self.assertEqual(api.submit("private", "local", "秘密")["status"], "completed")
            self.target.update(auth_mode="gemini", external=True)
            self.assertEqual(api.submit("private", "cloud", "秘密")["status"], "failed")
        self.assertEqual(runtime_mock.call_count, 1)

    def test_error_metadata_survives_without_raw_error_or_fallback(self):
        def runtime(*args):
            raise RuntimeError("secret-api-key private prompt")
        with patch.object(sdk, "run_isolated", side_effect=runtime), \
             patch.object(brain.lmstudio_client, "chat_completion", side_effect=AssertionError("fallback")):
            result = api.submit("sdk-thread", "bad", "合成データ")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["model_route"]["state"], "failed")
        self.assertIsNone(result["model_route"]["usage"])
        self.assertNotIn("secret-api-key", json.dumps(store.snapshot("sdk-thread")))
        self.assertFalse(result["model_route"]["fallback"])

    def test_restart_reconstructs_context_from_core_only(self):
        prompts = []
        def runtime(request_id, target, instructions, prompt, used, metadata):
            prompts.append(json.loads(prompt))
            return "保存された返答"
        with patch.object(sdk, "run_isolated", side_effect=runtime):
            api.submit("sdk-thread", "one", "最初")
            store.recover()
            api.submit("sdk-thread", "two", "続き")
        self.assertEqual(prompts[1]["history"].count({"role": "assistant", "content": "保存された返答"}), 1)
        self.assertEqual(prompts[1]["user_message"], "続き")

    def test_real_cancellation_watcher_closes_mock_sdk_agent(self):
        self.accepted()
        closed = []
        class Response:
            async def text(self):
                await asyncio.sleep(10)
        class Agent:
            conversation_id = "synthetic-sdk-session"
            def __init__(self, cfg): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): closed.append(True)
            async def chat(self, prompt): return Response()
        module = ModuleType("google.antigravity"); module.Agent = Agent
        async def run():
            async def cancel():
                await asyncio.sleep(.02)
                with db.get_connection() as connection:
                    connection.execute("UPDATE turns SET cancel_requested=1 WHERE request_id='sdk-request'")
            cancel_task = asyncio.create_task(cancel())
            try:
                with self.assertRaises(brain.TurnCancelled):
                    await sdk.execute_sdk("sdk-request", self.target, "instructions", "dummy", [], {})
            finally:
                await cancel_task
        with patch.dict(sys.modules, {"google.antigravity": module}), patch.object(sdk, "sdk_config", return_value=None):
            asyncio.run(run())
        self.assertEqual(closed, [True])

    def test_parent_deadline_terminates_owned_worker_during_sdk_startup(self):
        self.accepted()
        done = threading.Event()
        class Process:
            returncode = None
            def poll(self): return self.returncode
            def communicate(self, payload):
                done.wait(2)
                return "", "private stderr must not be exposed"
        process = Process()
        def stop(owned):
            self.assertIs(owned, process)
            process.returncode = -1
            done.set()
        target = {**self.target, "timeout_seconds": .01}
        with patch.object(sdk.subprocess, "Popen", return_value=process) as popen, \
             patch.object(sdk, "stop_worker", side_effect=stop) as cleanup:
            with self.assertRaises(TimeoutError):
                sdk.run_isolated("sdk-request", target, "instructions", "synthetic", [], {})
        cleanup.assert_called_once_with(process)
        self.assertEqual(popen.call_args.args[0][-1], "backend.antigravity_worker")
        self.assertNotIn("instructions", str(popen.call_args.args[0]))


class SDKRoutingContracts(unittest.TestCase):
    def test_local_is_loopback_only_and_cloud_is_explicitly_gated(self):
        with patch.object(sdk, "installed", return_value=True), patch.dict(os.environ, {
            "PETIT_ANTIGRAVITY_AUTH": "local", "PETIT_ANTIGRAVITY_MODEL": "fixture",
            "PETIT_ANTIGRAVITY_BASE_URL": "http://127.0.0.1:1234/v1"}):
            self.assertTrue(model_routing._antigravity_target("chat")["configured"])
            for address in ("https://example.com/v1", "http://user:pass@localhost/v1", "http://192.168.1.5/v1"):
                with patch.dict(os.environ, {"PETIT_ANTIGRAVITY_BASE_URL": address}):
                    self.assertFalse(model_routing._antigravity_target("chat")["configured"])
            with patch.dict(os.environ, {"PETIT_ANTIGRAVITY_AUTH": "gemini", "PETIT_ANTIGRAVITY_API_KEY": "hidden",
                                         "PETIT_ALLOW_ANTIGRAVITY_CLOUD": "false"}):
                self.assertFalse(model_routing._antigravity_target("chat")["configured"])
                self.assertNotIn("hidden", json.dumps(model_routing.public_status()))

    def test_legacy_completion_never_bypasses_sdk(self):
        from backend import lmstudio_client
        with lmstudio_client.observe_turn():
            lmstudio_client.set_prefetched_chat("text", "cached previous backend")
            with patch.object(lmstudio_client.httpx, "post") as http, self.assertRaises(lmstudio_client.LMStudioError):
                lmstudio_client.chat_completion([{"role": "user", "content": "text"}], target_override={"provider": "antigravity_sdk"})
        http.assert_not_called()


if __name__ == "__main__":
    unittest.main()
