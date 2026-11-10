"""Tests for archive API endpoints."""
import os
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from backend.main import app

TOKEN = "test_discord_service_token_32_characters_long_min!"


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PETIT_DISCORD_SERVICE_TOKEN", TOKEN)
    monkeypatch.setenv("PETIT_ARCHIVE_DIR", str(tmp_path / "archive"))
    return TestClient(app)


def test_archive_api_requires_auth(client: TestClient):
    resp = client.post("/api/channels/discord/archive/events", json={
        "message_id": "1", "guild_id": "1", "channel_id": "1", "author_id": "1", "created_at": "2026-11-10T00:00:00Z"
    })
    assert resp.status_code == 401


def test_archive_api_register_and_event(client: TestClient):
    headers = {"Authorization": f"Bearer {TOKEN}"}

    # Register channel 111 with manage_guild permission
    reg_resp = client.post(
        "/api/channels/discord/archive/register",
        headers=headers,
        json={
            "guild_id": "999",
            "author_id": "555",
            "channel_ids": ["111"],
            "enabled": True,
            "manage_guild": True,
        },
    )
    assert reg_resp.status_code == 200
    assert reg_resp.json()["status"] == "ok"

    # Send message event
    ev_resp = client.post(
        "/api/channels/discord/archive/events",
        headers=headers,
        json={
            "message_id": "12345",
            "guild_id": "999",
            "guild_name": "My Guild",
            "channel_id": "111",
            "channel_name": "dev",
            "author_id": "555",
            "author_name": "Alice",
            "content": "テストメッセージです。Discordアーカイブの動作確認。",
            "created_at": "2026-11-10T12:00:00Z",
        },
    )
    assert ev_resp.status_code == 200
    assert ev_resp.json()["status"] == "ok"
    assert ev_resp.json()["saved"] is True

    # Search via API
    search_resp = client.get(
        "/api/channels/discord/archive/search",
        headers=headers,
        params={"query": "テストメッセージ", "guild_id": "999"},
    )
    assert search_resp.status_code == 200
    data = search_resp.json()
    assert data["count"] == 1
    assert data["matches"][0]["message_id"] == "12345"
    assert data["matches"][0]["content"] == "テストメッセージです。Discordアーカイブの動作確認。"

    # Delete event (tombstone)
    del_resp = client.post(
        "/api/channels/discord/archive/delete",
        headers=headers,
        json={
            "message_id": "12345",
            "guild_id": "999",
            "channel_id": "111",
        },
    )
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "ok"

    # Search again -> should not return tombstoned message
    search_after_del = client.get(
        "/api/channels/discord/archive/search",
        headers=headers,
        params={"query": "テストメッセージ", "guild_id": "999"},
    )
    assert search_after_del.status_code == 200
    assert search_after_del.json()["count"] == 0
