"""Opt-in, read-only ACP v1 initialization probe for PETIT Develop.

Only performs initialize; never authenticates, opens a session, or sends a prompt.
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import signal
import subprocess
import threading
from typing import Any

AGENTS = {
    "codex": ("codex-acp",),
    "antigravity_cli": ("agy", "acp"),
}
ENV_ALLOW = {
    "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE",
    "LOCALAPPDATA", "APPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA",
}
MAX_LINE = 128 * 1024
INITIALIZE = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {
        "protocolVersion": 1,
        "clientCapabilities": {
            "auth": {"terminal": False},
            "fs": {"readTextFile": False, "writeTextFile": False},
            "terminal": False,
        },
        "clientInfo": {"name": "petit-develop-probe", "title": "PETIT Develop Probe", "version": "0.1.0"},
    },
}


def available() -> list[dict[str, Any]]:
    """No process launch, login, network traffic or filesystem scan beyond PATH."""
    rows = []
    for provider, command in AGENTS.items():
        rows.append({"provider": provider, "installed": bool(shutil.which(command[0])),
                     "transport": "acp-v1", "diagnostic": "not_run"})
    rows.append({"provider": "claude_code", "installed": bool(shutil.which("claude")),
                 "transport": "official-cli", "diagnostic": "acp_not_enabled",
                 "reason": "subscription_and_adapter_terms_require_review"})
    return rows


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError, ProcessLookupError):
        try:
            process.kill()
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def _safe_text(value: Any, limit: int = 80) -> str:
    return value[:limit] if isinstance(value, str) else ""


def _parse(line: bytes) -> dict[str, Any]:
    try:
        message = json.loads(line.decode("utf-8"))
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or message.get("id") != 1:
            return {"diagnostic": "invalid_response"}
        if "error" in message:
            return {"diagnostic": "rpc_error"}
        result = message.get("result")
        if not isinstance(result, dict) or result.get("protocolVersion") != 1:
            return {"diagnostic": "incompatible_protocol"}
        info = result.get("agentInfo") or {}
        caps = result.get("agentCapabilities") or {}
        methods = result.get("authMethods") or []
        if not isinstance(info, dict) or not isinstance(caps, dict) or not isinstance(methods, list):
            return {"diagnostic": "invalid_response"}
        return {"diagnostic": "initialized", "protocol_version": 1,
                "agent_name": _safe_text(info.get("name")),
                "load_session": caps.get("loadSession") is True,
                "auth_methods": [_safe_text(x.get("id"), 40) for x in methods[:12] if isinstance(x, dict)]}
    except (ValueError, UnicodeError, TypeError):
        return {"diagnostic": "invalid_response"}


def probe_command(command: list[str], *, timeout: float = 8) -> dict[str, Any]:
    """Initialize an ACP agent once, then terminate its complete process group.

    Child environment excludes PETIT API keys. No raw stdout/stderr is returned.
    """
    if not command or timeout <= 0 or timeout > 20:
        raise ValueError("invalid_probe_parameters")
    env = {key: value for key, value in os.environ.items() if key.upper() in ENV_ALLOW}
    output: queue.Queue[bytes | None] = queue.Queue(maxsize=1)
    process = None
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, env=env,
                                   **({"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
                                      if os.name == "nt" else {"start_new_session": True}))

        def read_one() -> None:
            try:
                output.put(process.stdout.readline(MAX_LINE + 1))
            except OSError:
                output.put(None)

        threading.Thread(target=read_one, daemon=True).start()
        process.stdin.write((json.dumps(INITIALIZE, ensure_ascii=True) + "\n").encode("utf-8"))
        process.stdin.flush()
        try:
            line = output.get(timeout=timeout)
        except queue.Empty:
            return {"diagnostic": "timeout"}
        if not line:
            return {"diagnostic": "closed_without_response"}
        if len(line) > MAX_LINE or not line.endswith(b"\n"):
            return {"diagnostic": "response_too_large"}
        return _parse(line)
    except (OSError, ValueError, BrokenPipeError):
        return {"diagnostic": "launch_failed"}
    finally:
        if process is not None:
            _stop(process)
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    stream.close()


def diagnose(provider: str, *, timeout: float = 8) -> dict[str, Any]:
    if provider == "claude_code":
        return next(item for item in available() if item["provider"] == provider)
    if provider not in AGENTS:
        raise ValueError("unknown_acp_provider")
    row = next(item for item in available() if item["provider"] == provider)
    if not row["installed"]:
        return {**row, "diagnostic": "not_installed"}
    return {**row, **probe_command(list(AGENTS[provider]), timeout=timeout)}
