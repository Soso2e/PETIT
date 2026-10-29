from __future__ import annotations

import asyncio
import hashlib
import io
import zipfile

from backend import antigravity_acp
from scripts import install_antigravity_acp


def test_status_separates_auth_usage_and_restrictions(monkeypatch, tmp_path):
    exe = tmp_path / "agy_acp_server.exe"
    exe.write_bytes(b"registry binary fixture")
    monkeypatch.setattr(antigravity_acp, "executable_path", lambda root_override=None: exe)
    monkeypatch.setattr(antigravity_acp, "sdk_version", lambda: "0.12.1")

    status = antigravity_acp.status()

    assert status["installed"] is True
    assert status["agent_version"] == tmp_path.name
    assert status["auth_mode"] == "oauth-personal"
    assert status["authenticated"] == "unknown"
    assert status["model"] == "unknown"
    assert status["token_usage"] == status["plan_quota"] == status["additional_credits"] == "unknown"
    assert status["local_filesystem_access"] == "disabled_until_os_sandbox_verified"
    assert status["general_chat_enabled"] is False
    assert status["background_enabled"] is False


def test_setup_client_denies_filesystem_and_terminal_requests():
    client = antigravity_acp._SetupClient()

    assert asyncio.run(client.request_permission("s", {}, [])) == {"outcome": {"outcome": "cancelled"}}
    for operation in (client.read_text_file("s", "C:/secret"),
                      client.write_text_file("s", "C:/secret", "data"),
                      client.create_terminal("s", "cmd.exe")):
        try:
            asyncio.run(operation)
        except PermissionError:
            pass
        else:
            raise AssertionError("ACP setup client must deny file and terminal capabilities")
    assert client.permissions_denied == 1


def test_verified_registry_install_uses_separate_versioned_location(monkeypatch, tmp_path):
    old_cli = tmp_path / "agy.exe"
    old_cli.write_bytes(b"existing cli")
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("agy_acp_server.exe", b"official acp fixture")
    archive_data = archive_buffer.getvalue()
    digest = hashlib.sha256(archive_data).hexdigest()
    monkeypatch.setattr(install_antigravity_acp, "registry_entry", lambda: ("1.4.3", {
        "archive": "https://dl.google.com/agent.zip", "cmd": "./agy_acp_server.exe", "sha256": digest
    }))
    monkeypatch.setattr(install_antigravity_acp, "read_url", lambda url, limit, hosts: archive_data)

    result = install_antigravity_acp.install(tmp_path / "antigravity-acp")

    installed = tmp_path / "antigravity-acp" / "1.4.3" / "agy_acp_server.exe"
    assert result["installed"] is True
    assert result["sha256"] == digest
    assert installed.read_bytes() == b"official acp fixture"
    assert old_cli.read_bytes() == b"existing cli"
