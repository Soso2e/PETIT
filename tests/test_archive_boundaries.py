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
    extract_attachment_text,
    ArchiveReconciler,
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


def test_channel_and_user_authorization_in_search(client: TestClient, configured_env: Path):
    """Users cannot see messages from channels they lack permission for (permitted_channels filter)."""
    headers = {"Authorization": f"Bearer {TOKEN}"}

    # Register both public channel 101 and admin secret channel 102
    client.post(
        "/api/channels/discord/archive/register",
        headers=headers,
        json={
            "guild_id": OTHER_GUILD_ID,
            "author_id": "99999",
            "channel_ids": ["101", "102"],
            "enabled": True,
            "manage_guild": True,
        },
    )

    # Ingest message in public channel 101
    client.post(
        "/api/channels/discord/archive/events",
        headers=headers,
        json={
            "message_id": "10001",
            "guild_id": OTHER_GUILD_ID,
            "channel_id": "101",
            "author_id": "1",
            "content": "全体公開のプロジェクト予算案",
            "created_at": "2026-11-10T10:00:00Z",
        },
    )

    # Ingest message in admin secret channel 102
    client.post(
        "/api/channels/discord/archive/events",
        headers=headers,
        json={
            "message_id": "10002",
            "guild_id": OTHER_GUILD_ID,
            "channel_id": "102",
            "author_id": "1",
            "content": "管理者限定の秘密予算案と役員報酬",
            "created_at": "2026-11-10T10:05:00Z",
        },
    )

    # 1. Search with general user permission (only channel 101 permitted)
    resp_general = client.get(
        "/api/channels/discord/archive/search",
        headers=headers,
        params={"query": "予算案", "guild_id": OTHER_GUILD_ID, "permitted_channels": "101"},
    )
    assert resp_general.status_code == 200
    gen_matches = resp_general.json()["matches"]
    assert len(gen_matches) == 1
    assert gen_matches[0]["message_id"] == "10001"
    assert "秘密予算案" not in gen_matches[0]["content"]

    # 2. Search with admin user permission (both channels 101 and 102 permitted)
    resp_admin = client.get(
        "/api/channels/discord/archive/search",
        headers=headers,
        params={"query": "予算案", "guild_id": OTHER_GUILD_ID, "permitted_channels": "101,102"},
    )
    assert resp_admin.status_code == 200
    admin_matches = resp_admin.json()["matches"]
    assert len(admin_matches) == 2
    found_ids = {m["message_id"] for m in admin_matches}
    assert found_ids == {"10001", "10002"}


@pytest.mark.anyio
async def test_archive_buffer_sqlite_persistence_across_process_restart(tmp_path: Path):
    """ArchiveBuffer survives process kill/restart without losing pending events in SQLite queue."""
    call_count = 0
    succeed = False

    class MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if not succeed:
                return httpx.Response(503, json={"error": "service unavailable"})
            return httpx.Response(200, json={"status": "ok", "saved": True})

    core = CoreClient(base_url="http://mock", token=TOKEN, transport=MockTransport())
    buffer_db = tmp_path / "persistent_buffer.sqlite"

    # Step 1: Process 1 pushes an event while Core is down, then suddenly terminates (simulated kill -9)
    buf1 = ArchiveBuffer(core, db_path=buffer_db, maxsize=10)
    buf1.push("event", {"message_id": "77701", "guild_id": "1", "channel_id": "1"})
    assert buf1.pending_count == 1
    # Terminate buf1 without delivering
    await buf1.stop()

    # Step 2: New Bot process restarts with the same buffer_db
    buf2 = ArchiveBuffer(core, db_path=buffer_db, maxsize=10)
    # The event is immediately loaded from SQLite on startup!
    assert buf2.pending_count == 1
    await buf2.start()

    # Core recovers
    succeed = True
    await asyncio.sleep(1.2)  # Wait for backoff retry
    assert buf2.pending_count == 0  # Delivered and cleared from SQLite!
    assert call_count >= 1

    await buf2.stop()
    await core.close()


def test_attachment_extraction_shielding_and_timeout():
    """Extracting corrupted PDFs or huge texts does not crash and respects limits."""
    # 1. Corrupted PDF garbage bytes should not crash
    corrupted_pdf = b"%PDF-1.4\ncorrupted garbage\x00\xff\xfe\x01\x02\x03\n%%EOF"
    result_corrupted = extract_attachment_text(corrupted_pdf, "broken.pdf")
    assert result_corrupted is None or isinstance(result_corrupted, str)

    # 2. Huge text file is bounded by max_chars
    huge_text = ("A" * 200000).encode("utf-8")
    result_huge = extract_attachment_text(huge_text, "huge.txt", max_chars=1000)
    assert result_huge is not None
    assert len(result_huge) == 1000

    # 3. Non-text unsupported extension returns None
    binary_data = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    assert extract_attachment_text(binary_data, "image.png") is None


def test_incremental_sync_and_edits(client: TestClient, configured_env: Path):
    """Message edits update archive FTS, and unregistering a channel immediately denies search."""
    headers = {"Authorization": f"Bearer {TOKEN}"}

    # Register channel 301
    client.post(
        "/api/channels/discord/archive/register",
        headers=headers,
        json={
            "guild_id": OWNER_GUILD_ID,
            "author_id": OWNER_ID,
            "channel_ids": ["301"],
            "enabled": True,
            "manage_guild": True,
        },
    )

    # 1. First revision of message
    client.post(
        "/api/channels/discord/archive/events",
        headers=headers,
        json={
            "message_id": "20001",
            "guild_id": OWNER_GUILD_ID,
            "channel_id": "301",
            "author_id": OWNER_ID,
            "content": "来週のリリース日時は未定です",
            "created_at": "2026-11-10T10:00:00Z",
        },
    )
    res1 = client.get(
        "/api/channels/discord/archive/search",
        headers=headers,
        params={"query": "未定です", "guild_id": OWNER_GUILD_ID},
    )
    assert res1.json()["count"] == 1

    # 2. Edited revision of message
    client.post(
        "/api/channels/discord/archive/events",
        headers=headers,
        json={
            "message_id": "20001",
            "guild_id": OWNER_GUILD_ID,
            "channel_id": "301",
            "author_id": OWNER_ID,
            "content": "来週のリリース日時は11月18日に確定しました",
            "created_at": "2026-11-10T10:00:00Z",
            "edited_at": "2026-11-10T10:30:00Z",
        },
    )
    # Old query no longer hits
    res_old = client.get(
        "/api/channels/discord/archive/search",
        headers=headers,
        params={"query": "未定です", "guild_id": OWNER_GUILD_ID},
    )
    assert res_old.json()["count"] == 0

    # New query hits updated text
    res_new = client.get(
        "/api/channels/discord/archive/search",
        headers=headers,
        params={"query": "11月18日", "guild_id": OWNER_GUILD_ID},
    )
    assert res_new.json()["count"] == 1
    assert "確定しました" in res_new.json()["matches"][0]["content"]

    # 3. Unregister channel 301 -> immediately excluded from search results!
    client.post(
        "/api/channels/discord/archive/register",
        headers=headers,
        json={
            "guild_id": OWNER_GUILD_ID,
            "author_id": OWNER_ID,
            "channel_ids": ["301"],
            "enabled": False,
            "manage_guild": True,
        },
    )
    res_after_unreg = client.get(
        "/api/channels/discord/archive/search",
        headers=headers,
        params={"query": "11月18日", "guild_id": OWNER_GUILD_ID},
    )
    assert res_after_unreg.json()["count"] == 0

