"""Reproduction and regression tests for archive boundaries, private threads, zone routing, and fault tolerance."""
import asyncio
import json
import os
from pathlib import Path
import httpx
import pytest
from starlette.testclient import TestClient

from backend.main import app
from backend import request_context
from backend.channels.discord.bot import ArchiveBuffer, CoreClient
from backend.discord_archive import (
    DiscordArchive,
    ArchivePolicy,
    ArchiveSearch,
    ArchiveIngestor,
    set_registrations,
)
from backend.tools import dispatch

TOKEN = "test_discord_service_token_32_characters_long_min!"
OWNER_ID = "123456789"
OWNER_GUILD_ID = "555"
OTHER_GUILD_ID = "999"


@pytest.fixture
def configured_env(tmp_path: Path, monkeypatch):
    archive_dir = tmp_path / "archive"
    monkeypatch.setenv("PETIT_DISCORD_SERVICE_TOKEN", TOKEN)
    monkeypatch.setenv("PETIT_DISCORD_OWNER_ID", OWNER_ID)
    monkeypatch.setenv("PETIT_DISCORD_OWNER_GUILD_IDS", OWNER_GUILD_ID)
    monkeypatch.setenv("PETIT_ARCHIVE_DIR", str(archive_dir))
    return archive_dir


@pytest.fixture
def client(configured_env):
    return TestClient(app)


def test_private_thread_boundary_enforcement(configured_env: Path):
    """Private threads must NOT inherit parent channel consent unless explicitly registered."""
    archive = DiscordArchive(configured_env / "personal.sqlite", zone="personal")

    # Parent channel 111 is registered, but thread 222 is NOT registered
    policy = ArchivePolicy({
        "enabled": True,
        "trust_zone": "personal",
        "allow_guilds": {
            OWNER_GUILD_ID: {"channels": ["111"]}
        }
    })
    ingestor = ArchiveIngestor(archive, policy)
    searcher = ArchiveSearch(archive, policy)

    # 1. Public thread message inherits parent consent
    pub_msg = {
        "message_id": "101",
        "guild_id": OWNER_GUILD_ID,
        "channel_id": "111",
        "thread_id": "222",
        "author_id": "1",
        "content": "公開スレッドの会話",
        "created_at": "2026-11-10T12:00:00Z",
        "is_private_thread": False,
    }
    assert ingestor.save_message(pub_msg) is True
    assert len(searcher.search("公開スレッド")) == 1

    # 2. Private thread message under the SAME parent channel MUST be rejected!
    priv_msg = {
        "message_id": "102",
        "guild_id": OWNER_GUILD_ID,
        "channel_id": "111",
        "thread_id": "333",
        "author_id": "1",
        "content": "秘密の非公開スレッドの会話",
        "created_at": "2026-11-10T12:05:00Z",
        "is_private_thread": True,
    }
    assert ingestor.save_message(priv_msg) is False
    assert len(searcher.search("非公開スレッド")) == 0

    # 3. Explicitly registering private thread 333 permits ingestion
    policy_with_thread = ArchivePolicy({
        "enabled": True,
        "trust_zone": "personal",
        "allow_guilds": {
            OWNER_GUILD_ID: {"channels": ["111", "333"]}
        }
    })
    ingestor_explicit = ArchiveIngestor(archive, policy_with_thread)
    searcher_explicit = ArchiveSearch(archive, policy_with_thread)

    assert ingestor_explicit.save_message(priv_msg) is True
    assert len(searcher_explicit.search("非公開スレッド")) == 1


def test_personal_and_guild_zone_routing_and_isolation(client: TestClient, configured_env: Path):
    """Messages from owner designated guilds route to personal zone; other guilds route to guild zone."""
    headers = {"Authorization": f"Bearer {TOKEN}"}

    # 1. Register channels in Owner guild (routes to personal zone)
    reg_owner = client.post(
        "/api/channels/discord/archive/register",
        headers=headers,
        json={
            "guild_id": OWNER_GUILD_ID,
            "author_id": OWNER_ID,
            "channel_ids": ["101"],
            "enabled": True,
            "manage_guild": True,
        },
    )
    assert reg_owner.status_code == 200
    assert reg_owner.json()["zone"] == "personal"

    # 2. Register channels in Other guild (routes to guild_999 zone)
    reg_other = client.post(
        "/api/channels/discord/archive/register",
        headers=headers,
        json={
            "guild_id": OTHER_GUILD_ID,
            "author_id": "99999",
            "channel_ids": ["201"],
            "enabled": True,
            "manage_guild": True,
        },
    )
    assert reg_other.status_code == 200
    assert reg_other.json()["zone"] == f"guild_{OTHER_GUILD_ID}"

    # Verify separate sqlite files created
    assert (configured_env / "personal.allowlist.json").exists()
    assert (configured_env / f"guild_{OTHER_GUILD_ID}.allowlist.json").exists()

    # Post message in Owner guild -> personal.sqlite
    ev_personal = client.post(
        "/api/channels/discord/archive/events",
        headers=headers,
        json={
            "message_id": "1",
            "guild_id": OWNER_GUILD_ID,
            "channel_id": "101",
            "author_id": OWNER_ID,
            "content": "Ownerの個人タスク: 確定申告の準備",
            "created_at": "2026-11-10T10:00:00Z",
        },
    )
    assert ev_personal.status_code == 200
    assert ev_personal.json()["zone"] == "personal"

    # Post message in Other guild -> guild_999.sqlite
    ev_guild = client.post(
        "/api/channels/discord/archive/events",
        headers=headers,
        json={
            "message_id": "2",
            "guild_id": OTHER_GUILD_ID,
            "channel_id": "201",
            "author_id": "99999",
            "content": "学校プロジェクト: 数学課題レポートの提出期限",
            "created_at": "2026-11-10T11:00:00Z",
        },
    )
    assert ev_guild.status_code == 200
    assert ev_guild.json()["zone"] == f"guild_{OTHER_GUILD_ID}"

    # Search in personal zone via Tool
    personal_res = json.loads(dispatch("search_discord_archive", {"query": "確定申告"}))
    assert personal_res["count"] == 1
    assert personal_res["matches"][0]["message_id"] == "1"

    # Search in other guild zone via Tool (by specifying guild_id in owner context)
    guild_res = json.loads(dispatch("search_discord_archive", {"query": "数学課題", "guild_id": OTHER_GUILD_ID}))
    assert guild_res["count"] == 1
    assert guild_res["matches"][0]["message_id"] == "2"


def test_registration_permission_checks(client: TestClient):
    """Unauthorized callers cannot register channels or alter Personal Zone."""
    headers = {"Authorization": f"Bearer {TOKEN}"}

    # 1. Non-owner trying to modify Personal Zone -> 403 Forbidden
    res_fake_owner = client.post(
        "/api/channels/discord/archive/register",
        headers=headers,
        json={
            "guild_id": OWNER_GUILD_ID,
            "author_id": "666666",
            "channel_ids": ["999"],
            "enabled": True,
            "manage_guild": True,
            "zone": "personal",
        },
    )
    assert res_fake_owner.status_code == 403
    assert "Owner のみ" in res_fake_owner.json()["detail"]

    # 2. Non-admin trying to register Guild Zone without Manage Server -> 403 Forbidden
    res_no_perm = client.post(
        "/api/channels/discord/archive/register",
        headers=headers,
        json={
            "guild_id": OTHER_GUILD_ID,
            "author_id": "777777",
            "channel_ids": ["123"],
            "enabled": True,
            "manage_guild": False,
            "permissions": 0,
        },
    )
    assert res_no_perm.status_code == 403
    assert "管理権限" in res_no_perm.json()["detail"]


@pytest.mark.anyio
async def test_archive_buffer_retry_on_core_outage():
    """ArchiveBuffer holds and retries events when Core is temporarily unavailable."""
    call_count = 0
    succeed = False

    class MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if not succeed:
                return httpx.Response(503, json={"error": "temporarily unavailable"})
            return httpx.Response(200, json={"status": "ok", "saved": True})

    core = CoreClient(base_url="http://mock", token=TOKEN, transport=MockTransport())
    buffer = ArchiveBuffer(core, maxsize=10)
    await buffer.start()

    # Push event while Core is down
    buffer.push("event", {"message_id": "9999", "guild_id": "1", "channel_id": "1"})
    await asyncio.sleep(0.1)
    assert call_count >= 1
    assert buffer.pending_count == 1  # Retained in buffer!

    # Core recovers
    succeed = True
    await asyncio.sleep(1.2)  # Wait for backoff retry
    assert buffer.pending_count == 0  # Successfully delivered and cleared!
    assert call_count >= 2

    await buffer.stop()
    await core.close()


def test_attachment_text_extraction_and_fts_search(client: TestClient, configured_env: Path):
    """Attachments with extracted text are indexed in SQLite FTS5 and searchable via PETIT tool."""
    headers = {"Authorization": f"Bearer {TOKEN}"}

    # Register channel in Owner guild
    client.post(
        "/api/channels/discord/archive/register",
        headers=headers,
        json={
            "guild_id": OWNER_GUILD_ID,
            "author_id": OWNER_ID,
            "channel_ids": ["501"],
            "enabled": True,
            "manage_guild": True,
        },
    )

    # Post message with attached document text (e.g. extracted from PDF/MD)
    msg_with_attachment = {
        "message_id": "8881",
        "guild_id": OWNER_GUILD_ID,
        "channel_id": "501",
        "author_id": OWNER_ID,
        "content": "添付資料を共有します",
        "created_at": "2026-11-10T14:00:00Z",
        "attachments": [
            {
                "id": "att_1",
                "filename": "PETIT_architecture_v2.pdf",
                "content_type": "application/pdf",
                "size": 1024,
                "url": "https://cdn.discordapp.com/attachments/501/att_1/doc.pdf",
                "extracted_text": "【PETIT アーキテクチャ第2版】Brain ルーティングと Durable Read Task の連携仕様",
            }
        ],
    }

    res = client.post("/api/channels/discord/archive/events", headers=headers, json=msg_with_attachment)
    assert res.status_code == 200
    assert res.json()["saved"] is True

    # Search for keyword present ONLY inside the attachment extracted_text!
    tool_result = json.loads(dispatch("search_discord_archive", {"query": "Durable Read Task"}))
    assert tool_result["count"] == 1
    hit = tool_result["matches"][0]
    assert hit["message_id"] == "8881"
    assert hit["content"] == "添付資料を共有します"
    assert len(hit["attachments"]) == 1
    assert hit["attachments"][0]["filename"] == "PETIT_architecture_v2.pdf"
    assert "Durable Read Task" in hit["attachments"][0]["extracted_snippet"]
    assert hit["discord_url"] == "https://discord.com/channels/555/501/8881"

    # Verify idempotency on redelivery (e.g. buffer retry / duplicate event)
    res_duplicate = client.post("/api/channels/discord/archive/events", headers=headers, json=msg_with_attachment)
    assert res_duplicate.status_code == 200
    assert res_duplicate.json()["status"] == "ok"
    assert res_duplicate.json()["saved"] is False  # Correctly recognized as duplicate and skipped

    # Search count must still be exactly 1, no duplicate entries!
    tool_result_after_dup = json.loads(dispatch("search_discord_archive", {"query": "Durable Read Task"}))
    assert tool_result_after_dup["count"] == 1
