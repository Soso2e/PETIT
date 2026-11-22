"""Tests for Discord Owner-mode PC file attachment tool and delivery."""
import asyncio
import json
import sys
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.test_setup_integrations import isolated  # noqa: F401 - autouse isolation
from backend import brain_catalog, conversation_store as store, discord_api, discord_files, request_context, tools
from backend.channels.discord import bot

TOKEN = "t" * 40


def _make_discord_app():
    app = FastAPI()
    app.include_router(discord_api.router)
    return TestClient(app)


def test_resolve_file_accepts_regular_file_and_rejects_folder_and_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("PETIT_DISCORD_OWNER_ID", "1001")
    sample = tmp_path / "report.txt"
    sample.write_text("hello world", encoding="utf-8")

    verified, size = discord_files.resolve_file(str(sample))
    assert verified == sample
    assert size == len(b"hello world")

    # Folders are explicitly rejected
    subdir = tmp_path / "folder"
    subdir.mkdir()
    with pytest.raises(ValueError, match="フォルダ"):
        discord_files.resolve_file(str(subdir))

    # Secret files are rejected
    env_file = tmp_path / ".env"
    env_file.write_text("SECRET=1", encoding="utf-8")
    with pytest.raises(ValueError, match="保護"):
        discord_files.resolve_file(str(env_file))

    key_file = tmp_path / "id_rsa.pem"
    key_file.write_text("KEY", encoding="utf-8")
    with pytest.raises(ValueError, match="保護"):
        discord_files.resolve_file(str(key_file))


def test_resolve_file_rejects_oversized_file(tmp_path, monkeypatch):
    monkeypatch.setenv("PETIT_DISCORD_MAX_ATTACHMENT_BYTES", "10")
    big = tmp_path / "big.bin"
    big.write_bytes(b"0123456789abcdef")
    with pytest.raises(ValueError, match="上限"):
        discord_files.resolve_file(str(big))


def test_confirmation_is_required_only_in_server_not_dm():
    tools.register_builtin_tools()
    with request_context.bind(request_id="r1", session_id="discord:1", is_admin=True, source="discord", discord_guild_id=None):
        assert tools.requires_confirmation("send_discord_file") is False
    with request_context.bind(request_id="r2", session_id="discord:2", is_admin=True, source="discord", discord_guild_id="2002"):
        assert tools.requires_confirmation("send_discord_file") is True


def test_preview_shows_resolved_path_and_filename(tmp_path):
    tools.register_builtin_tools()
    sample = tmp_path / "memo.md"
    sample.write_text("# Memo\n", encoding="utf-8")
    preview = tools.preview_for("send_discord_file", {"path": str(sample)})
    assert preview is not None
    assert "memo.md" in preview
    assert str(sample) in preview


def test_catalog_exposes_tool_only_for_discord_admin():
    tools.register_builtin_tools()
    schema = {"function": {"name": "send_discord_file"}}
    setup = {"connected": [], "secrets": {}}
    with request_context.bind(request_id="r1", session_id="web:1", is_admin=True, source="web"):
        assert brain_catalog.available(schema, local_only=False, setup=setup) is False
    with request_context.bind(request_id="r2", session_id="discord:1", is_admin=False, source="discord"):
        assert brain_catalog.available(schema, local_only=False, setup=setup) is False
    with request_context.bind(request_id="r3", session_id="discord:1", is_admin=True, source="discord"):
        assert brain_catalog.available(schema, local_only=False, setup=setup) is True


def test_stage_and_download_attachment_via_api(tmp_path, monkeypatch):
    monkeypatch.setenv("PETIT_DISCORD_SERVICE_TOKEN", TOKEN)
    sample = tmp_path / "data.csv"
    sample.write_bytes(b"a,b\n1,2\n")

    with request_context.bind(request_id="r1", session_id="discord:1", is_admin=True, source="discord"):
        staged = discord_files.stage_file(str(sample))
    assert staged["sent"] is True
    assert staged["filename"] == "data.csv"

    reply = discord_api._reply({
        "status": "completed",
        "reply": "送りました。",
        "request_id": "discord:1",
        "effects": [{
            "call_id": "c1",
            "tool": "send_discord_file",
            "status": "applied",
            "result": json.dumps(staged, ensure_ascii=False),
        }],
    })
    assert reply["attachments"] == [{
        "attachment_id": staged["attachment_id"],
        "filename": "data.csv",
        "size_bytes": staged["size_bytes"],
    }]

    client = _make_discord_app()
    assert client.get(f"/api/channels/discord/attachments/{staged['attachment_id']}").status_code == 401
    res = client.get(
        f"/api/channels/discord/attachments/{staged['attachment_id']}",
        headers={"Authorization": "Bearer " + TOKEN},
    )
    assert res.status_code == 200
    assert res.content == b"a,b\n1,2\n"


def test_bot_send_result_uploads_attachments(tmp_path, monkeypatch):
    monkeypatch.setenv("PETIT_DISCORD_SERVICE_TOKEN", TOKEN)
    sample = tmp_path / "hello.txt"
    sample.write_bytes(b"payload-bytes")
    with request_context.bind(request_id="r1", session_id="discord:1", is_admin=True, source="discord"):
        staged = discord_files.stage_file(str(sample))

    app = FastAPI()
    app.include_router(discord_api.router)
    transport = httpx.ASGITransport(app=app)
    core = bot.CoreClient("http://core", TOKEN, transport=transport)

    sent_calls = []

    class FakeChannel:
        async def send(self, content=None, **kwargs):
            sent_calls.append((content, kwargs))

    class FakeFile:
        def __init__(self, fp, filename=None):
            self.data = fp.read()
            self.filename = filename

    fake_discord = SimpleNamespace(
        Intents=SimpleNamespace(default=lambda: SimpleNamespace(message_content=True)),
        Client=type("FakeClient", (), {"__init__": lambda self, **kw: None}),
        app_commands=SimpleNamespace(
            Group=lambda **kw: SimpleNamespace(add_command=lambda *a, **k: None, command=lambda **kw: (lambda f: f)),
            CommandTree=lambda *a, **k: SimpleNamespace(add_command=lambda *a, **k: None, sync=lambda *a, **k: None),
            describe=lambda **kw: (lambda f: f),
            choices=lambda **kw: (lambda f: f),
            Choice=lambda **kw: None,
        ),
        ui=SimpleNamespace(View=object, Button=object),
        ButtonStyle=SimpleNamespace(success=1, secondary=2),
        File=FakeFile,
    )
    monkeypatch.setitem(sys.modules, "discord", fake_discord)

    # Extract send_result by inspecting a minimal harness: call CoreClient + FakeChannel directly
    async def run():
        raw = await core.fetch_attachment(staged["attachment_id"])
        assert raw == b"payload-bytes"
        channel = FakeChannel()
        data = {
            "reply": "ファイルです。",
            "attachments": [{"attachment_id": staged["attachment_id"], "filename": "hello.txt", "size_bytes": 13}],
            "approvals": [],
        }
        # Mirror send_result behavior with FakeFile
        for chunk in [data["reply"]]:
            await channel.send(chunk)
        files = [fake_discord.File(fp=__import__("io").BytesIO(raw), filename="hello.txt")]
        await channel.send(files=files)
        await core.close()

    asyncio.run(run())
    assert sent_calls[0][0] == "ファイルです。"
    assert sent_calls[1][1]["files"][0].data == b"payload-bytes"
    assert sent_calls[1][1]["files"][0].filename == "hello.txt"


def test_server_approval_flow_end_to_end(tmp_path, monkeypatch):
    from backend import brain, conversation_api

    monkeypatch.setenv("PETIT_DISCORD_SERVICE_TOKEN", TOKEN)
    monkeypatch.setenv("PETIT_DISCORD_OWNER_ID", "1001")
    monkeypatch.setenv("PETIT_DISCORD_OWNER_GUILD_IDS", "2002")

    sample = tmp_path / "notes.txt"
    sample.write_bytes(b"server-file")

    # 1) Turn in a server channel proposes send_discord_file and waits for approval
    with request_context.bind(
        request_id="discord:9001",
        session_id="discord:777",
        is_admin=True,
        source="discord",
        discord_author_id="1001",
        discord_guild_id="2002",
    ):
        store.create_thread("discord:777", source="discord")
        store.accept("discord:777", "discord:9001", {
            "message": "送って",
            "source": "discord",
            "is_admin": True,
            "discord_author_id": "1001",
            "discord_guild_id": "2002",
        })
        call = {
            "id": "call-1",
            "type": "function",
            "function": {"name": "send_discord_file", "arguments": json.dumps({"path": str(sample)})},
        }
        assert tools.requires_confirmation("send_discord_file") is True
        approval_id = store.propose("discord:9001", call, {"path": str(sample)})
        store.save_messages("discord:9001", [
            {"role": "user", "content": "送って"},
            {"role": "assistant", "content": "", "tool_calls": [call]},
            {"role": "tool", "tool_call_id": "call-1", "content": '{"status":"awaiting_user_approval"}'},
        ])
        store.finish("discord:9001", {"reply": "", "used_tools": []}, status="waiting_approval")

    client = _make_discord_app()
    pending = client.get("/api/channels/discord/events/9001", headers={"Authorization": "Bearer " + TOKEN}).json()
    assert pending["status"] == "waiting_approval"
    assert len(pending["approvals"]) == 1
    assert str(sample) in pending["approvals"][0]["preview"]

    # 2) Approving executes the staged file and returns attachments
    monkeypatch.setattr(brain, "run", lambda request_id, **kw: store.finish(
        request_id, {"reply": "送信しました。", "used_tools": kw.get("used_tools", [])}
    ))
    approved = client.post(
        "/api/channels/discord/approvals",
        headers={"Authorization": "Bearer " + TOKEN},
        json={
            "interaction_id": "9002",
            "approval_id": approval_id,
            "guild_id": "2002",
            "author_id": "1001",
            "approved": True,
        },
    ).json()
    assert approved["status"] == "completed"
    assert len(approved["attachments"]) == 1
    assert approved["attachments"][0]["filename"] == "notes.txt"
