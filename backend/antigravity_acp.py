"""Standard ACP client for the official Google Antigravity ACP agent.

This module intentionally exposes setup/handshake operations only. General chat,
background work, filesystem access and terminal access remain disabled until PETIT
can enforce the required OS-level sandbox and the user explicitly starts a
single-user interactive development task.
"""
from __future__ import annotations

import asyncio
import importlib.metadata
import os
from pathlib import Path
import platform

SDK_DISTRIBUTION = "agent-client-protocol"
REGISTRY_ID = "antigravity-acp"
DEFAULT_ROOT = Path(os.getenv("LOCALAPPDATA") or Path.home() / ".local" / "share") / "PETIT" / "antigravity-acp"


def executable_path(root_override: str | Path | None = None) -> Path:
    override = os.getenv("PETIT_ANTIGRAVITY_ACP_EXECUTABLE", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    root = Path(root_override).expanduser().resolve() if root_override else DEFAULT_ROOT
    versions = sorted((item for item in root.iterdir() if item.is_dir()), reverse=True) if root.is_dir() else []
    executable = "agy_acp_server.exe" if os.name == "nt" else "agy_acp_server.par"
    for version in versions:
        candidate = version / executable
        if candidate.is_file():
            return candidate
    return Path()


def sdk_version() -> str | None:
    try:
        return importlib.metadata.version(SDK_DISTRIBUTION)
    except importlib.metadata.PackageNotFoundError:
        return None


def status(root_override: str | Path | None = None) -> dict:
    executable = executable_path(root_override)
    return {"provider": "antigravity_acp", "registry_id": REGISTRY_ID,
            "installed": bool(str(executable) and executable.is_file()),
            "executable": str(executable) if str(executable) and executable.is_file() else None,
            "agent_version": executable.parent.name if str(executable) and executable.is_file() else "unknown",
            "client_sdk_version": sdk_version() or "missing", "auth_mode": "oauth-personal",
            "authenticated": "unknown", "model": "unknown", "token_usage": "unknown",
            "plan_quota": "unknown", "additional_credits": "unknown",
            "local_filesystem_access": "disabled_until_os_sandbox_verified",
            "general_chat_enabled": False, "background_enabled": False,
            "platform": platform.platform(), "last_error": None}


class _SetupClient:
    def __init__(self):
        self.connection = None
        self.updates: list[dict] = []
        self.permissions_denied = 0

    def on_connect(self, connection):
        self.connection = connection

    async def session_update(self, session_id, update, **kwargs):
        # Retain protocol metadata only; never persist prompt/tool content in setup logs.
        name = type(update).__name__
        self.updates.append({"kind": name, "at": time.monotonic()})

    async def request_permission(self, session_id, tool_call, options, **kwargs):
        self.permissions_denied += 1
        return {"outcome": {"outcome": "cancelled"}}

    async def read_text_file(self, session_id, path, line=None, limit=None, **kwargs):
        raise PermissionError("filesystem access is disabled")

    async def write_text_file(self, session_id, path, content, **kwargs):
        raise PermissionError("filesystem access is disabled")

    async def create_terminal(self, session_id, command, args=None, **kwargs):
        raise PermissionError("terminal access is disabled")


def _agent_command() -> Path:
    path = executable_path()
    if not str(path) or not path.is_file():
        raise RuntimeError("agent_not_installed")
    return path


async def inspect_agent() -> dict:
    from acp import PROTOCOL_VERSION, spawn_agent_process
    client = _SetupClient()
    async with spawn_agent_process(client, str(_agent_command())) as (connection, process):
        initialized = await asyncio.wait_for(connection.initialize(protocol_version=PROTOCOL_VERSION), timeout=20)
        methods = getattr(initialized, "auth_methods", None) or []
        return {"ok": True, "provider": "antigravity_acp", "protocol_version": getattr(initialized, "protocol_version", None),
                "agent_info": getattr(initialized, "agent_info", None).model_dump() if getattr(initialized, "agent_info", None) else None,
                "auth_methods": [item.model_dump() if hasattr(item, "model_dump") else dict(item) for item in methods],
                "process_running": process.returncode is None, "session_id": "not_created",
                "authenticated": "unknown", "model": "unknown", "token_usage": "unknown",
                "plan_quota": "unknown", "additional_credits": "unknown",
                "permissions_denied": client.permissions_denied}


async def authenticate_personal() -> dict:
    """Start only an Agent-advertised protocol login explicitly requested by the user."""
    from acp import PROTOCOL_VERSION, spawn_agent_process
    client = _SetupClient()
    async with spawn_agent_process(client, str(_agent_command())) as (connection, process):
        initialized = await asyncio.wait_for(connection.initialize(protocol_version=PROTOCOL_VERSION), timeout=30)
        methods = getattr(initialized, "auth_methods", None) or []
        candidates = [item for item in methods if getattr(item, "id", None) == "oauth-personal"
                      and getattr(item, "type", "agent") != "terminal"]
        if len(candidates) != 1:
            raise RuntimeError("official_oauth_personal_method_unavailable")
        await asyncio.wait_for(connection.authenticate(method_id="oauth-personal"), timeout=300)
        return {"ok": True, "provider": "antigravity_acp", "auth_mode": "oauth-personal",
                "authenticated": "agent_auth_call_succeeded", "credentials_saved_by": "official_agent",
                "credentials_returned_to_petit": False, "plan_quota": "unknown", "additional_credits": "unknown"}


def run_async(coro):
    return asyncio.run(coro)
