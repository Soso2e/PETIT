"""ACP initialization probe: real local fake process, no external accounts."""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock

from backend import develop_acp as acp


class DevelopAcpTests(unittest.TestCase):
    def test_capabilities_deny_files_terminal_auth(self):
        flags = acp.INITIALIZE["params"]["clientCapabilities"]
        self.assertEqual(flags["fs"], {"readTextFile": False, "writeTextFile": False})
        self.assertFalse(flags["terminal"])
        self.assertFalse(flags["auth"]["terminal"])

    def test_parse_minimal_initialize(self):
        result = acp._parse(json.dumps({"jsonrpc": "2.0", "id": 1, "result": {
            "protocolVersion": 1, "agentInfo": {"name": "test-agent"},
            "agentCapabilities": {"loadSession": True}, "authMethods": [{"id": "oauth-personal"}]}}).encode())
        self.assertEqual(result["diagnostic"], "initialized")
        self.assertEqual(result["auth_methods"], ["oauth-personal"])
        self.assertTrue(result["load_session"])

    def test_wrong_protocol(self):
        line = b'{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":2}}'
        self.assertEqual(acp._parse(line)["diagnostic"], "incompatible_protocol")

    def test_invalid_and_error_are_sanitized(self):
        self.assertEqual(acp._parse(b'private key')["diagnostic"], "invalid_response")
        payload = b'{"jsonrpc":"2.0","id":1,"error":{"message":"secret token"}}'
        self.assertEqual(acp._parse(payload), {"diagnostic": "rpc_error"})

    def test_fake_agent_process_initialize(self):
        program = ('import sys,json;msg=json.loads(sys.stdin.readline());'
                   'assert msg["method"]=="initialize";'
                   'print(json.dumps({"jsonrpc":"2.0","id":1,"result":'
                   '{"protocolVersion":1,"agentInfo":{"name":"fake"},'
                   '"agentCapabilities":{},"authMethods":[]}}),flush=True)')
        result = acp.probe_command([sys.executable, "-u", "-c", program], timeout=3)
        self.assertEqual(result["diagnostic"], "initialized")
        self.assertEqual(result["agent_name"], "fake")

    def test_timeout_terminates_process(self):
        program = 'import time;time.sleep(5)'
        result = acp.probe_command([sys.executable, "-u", "-c", program], timeout=0.2)
        self.assertEqual(result["diagnostic"], "timeout")

    def test_no_secrets_forwarded(self):
        program = ('import os,sys,json;sys.stdin.readline();'
                   'print(json.dumps({"jsonrpc":"2.0","id":1,"result":'
                   '{"protocolVersion":1,"agentInfo":{"name":os.getenv("PETIT_SECRET_TEST", "clean")}}}),flush=True)')
        with mock.patch.dict(os.environ, {"PETIT_SECRET_TEST": "leaked"}):
            result = acp.probe_command([sys.executable, "-u", "-c", program], timeout=3)
        self.assertEqual(result["agent_name"], "clean")

    def test_claude_not_launched(self):
        with mock.patch.object(acp, "probe_command", side_effect=AssertionError("must not launch")):
            self.assertEqual(acp.diagnose("claude_code")["diagnostic"], "acp_not_enabled")


if __name__ == "__main__":
    unittest.main()
