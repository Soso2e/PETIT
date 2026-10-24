"""No-credential contracts. These do not prove a live Antigravity response."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import probe_antigravity_sdk as probe


class ProbeContracts(unittest.TestCase):
    def test_missing_key_is_skipped_without_entering_sdk(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": ""}), patch.object(probe, "live_probe") as live:
            report = probe.run(live=True, backend="gemini")
        self.assertEqual(report["status"], "skipped")
        self.assertFalse(report["network_invoked"])
        live.assert_not_called()

    def test_error_text_is_never_put_in_report(self):
        async def broken(*args):
            raise RuntimeError("secret-key and private prompt")
        with patch.dict("os.environ", {"GEMINI_API_KEY": "synthetic"}), patch.object(probe, "live_probe", broken):
            report = probe.run(live=True, backend="gemini")
        self.assertEqual(report["reason"], "sdk_error")
        self.assertNotIn("secret-key", json.dumps(report))
        self.assertFalse(report["issue_349_complete"])

    def test_timeout_is_failure(self):
        async def timeout(*args):
            raise TimeoutError()
        with patch.dict("os.environ", {"GEMINI_API_KEY": "synthetic"}), patch.object(probe, "live_probe", timeout):
            report = probe.run(live=True, backend="gemini")
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["reason"], "timeout_or_cancel")


class RealSDKConfiguration(unittest.TestCase):
    def test_installed_sdk_restricts_tools_and_uses_separate_storage(self):
        try:
            from google.antigravity import Agent
        except ImportError:
            self.skipTest("optional SDK is tested in the isolated SDK environment")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cfg = probe.make_config(root, api_key="synthetic-no-network")
            self.assertIsNotNone(Agent(cfg))
            self.assertEqual([x.value for x in cfg.capabilities.enabled_tools], ["finish"])
            for name in ("tools", "mcp_servers", "skills_paths", "inline_skills", "subagents", "triggers"):
                self.assertEqual(getattr(cfg, name), [])
            self.assertTrue(Path(cfg.app_data_dir).is_relative_to(root))
            self.assertTrue(Path(cfg.save_dir).is_relative_to(root))


if __name__ == "__main__":
    unittest.main()
