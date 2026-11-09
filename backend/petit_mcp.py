"""PETIT MCP server (stdio). Started by a CLI agent; relays PETIT Tools to Core.

Environment (set by Core when it launches the CLI):
  PETIT_CORE_URL      e.g. http://127.0.0.1:8000
  PETIT_BRIDGE_TOKEN  one-Turn token from agent_bridge.issue()

Protocol: newline-delimited JSON-RPC 2.0 over stdin/stdout (MCP stdio transport).
Nothing but protocol messages is written to stdout.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Callable

import httpx

SUPPORTED_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "petit", "version": "1"}


class Bridge:
    def __init__(self, base_url: str, token: str, transport: httpx.BaseTransport | None = None):
        self._client = httpx.Client(base_url=base_url.rstrip("/"), timeout=httpx.Timeout(120, connect=10),
                                    transport=transport, headers={"Authorization": "Bearer " + token})

    def post(self, path: str, body: dict | None = None) -> dict:
        response = self._client.post(path, json=body or {})
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = None
            raise BridgeError(str(detail or f"PETIT Core error {response.status_code}"))
        return response.json()


class BridgeError(RuntimeError):
    pass


def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def handle(message: dict, bridge: Bridge) -> dict | None:
    """Return a JSON-RPC response, or None for notifications."""
    method = message.get("method")
    msg_id = message.get("id")
    if msg_id is None:
        return None  # notifications (e.g. notifications/initialized) need no reply

    def ok(result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def error(code: int, text: str) -> dict:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": text}}

    params = message.get("params") or {}
    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
        return ok({"protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": SERVER_INFO,
                   "instructions": "PETIT Core の Tool。確認が必要な操作は承認待ちを返す。承認前に実行済みと言わない。"})
    if method == "ping":
        return ok({})
    try:
        if method == "tools/list":
            listed = bridge.post("/api/agent-bridge/tools/list")["tools"]
            return ok({"tools": [{"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"],
                                  "annotations": {"readOnlyHint": t.get("risk") == "safe_read"}} for t in listed]})
        if method == "tools/call":
            name = params.get("name")
            if not isinstance(name, str):
                return error(-32602, "name is required")
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                return error(-32602, "arguments must be an object")
            data = bridge.post("/api/agent-bridge/tools/call", {"name": name, "arguments": arguments})
            return ok({"content": [{"type": "text", "text": _text(data.get("result"))}],
                       "isError": bool(data.get("isError"))})
    except (BridgeError, httpx.HTTPError, ValueError, KeyError) as exc:
        if method == "tools/call":
            # Tool-level failures are results the model can read, not protocol errors.
            return ok({"content": [{"type": "text", "text": f"PETIT Core に届きませんでした: {exc}"}], "isError": True})
        return error(-32603, str(exc))
    return error(-32601, f"method not found: {method}")


def serve(stdin, stdout, bridge: Bridge, log: Callable[[str], None] = lambda s: None) -> None:
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            response = handle(message, bridge) if isinstance(message, dict) else \
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()


def main() -> None:
    token = os.environ.get("PETIT_BRIDGE_TOKEN", "")
    if not token:
        print("PETIT_BRIDGE_TOKEN が設定されていません。", file=sys.stderr)
        raise SystemExit(2)
    bridge = Bridge(os.environ.get("PETIT_CORE_URL", "http://127.0.0.1:8000"), token)
    serve(sys.stdin, sys.stdout, bridge)


if __name__ == "__main__":
    main()
