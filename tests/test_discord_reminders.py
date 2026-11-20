"""Tests for Discord-only channel reminders (Owner mode, Guild mode, and Bot delivery)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.test_setup_integrations import isolated  # noqa: F401 - autouse isolation
from backend import (
    brain_catalog,
    config,
    db,
    discord_api,
    discord_reminders,
    guild_api,
    lmstudio_client,
    reminders,
    request_context,
    tools,
)
from backend.channels.discord import bot, relay
from backend.tools import builtins
from backend.tools import discord_reminders as discord_reminder_tools

TOKEN = "r" * 40
OWNER = "1001"
GUILD_A = "8001"
MEMBER_A = "9001"
MEMBER_B = "9002"
CHANNEL_ID = "777001"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STORAGE_DIR", tmp_path / "storage")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "storage" / "app.db")
    monkeypatch.setenv("PETIT_DISCORD_SERVICE_TOKEN", TOKEN)
    monkeypatch.setenv("PETIT_DISCORD_OWNER_ID", OWNER)
    monkeypatch.setenv("PETIT_DISCORD_OWNER_GUILD_IDS", "2002")
    monkeypatch.setenv("PETIT_DISCORD_GUILD_MODE", "on")
    monkeypatch.setenv("PETIT_DEEPSEEK_API_KEY", "sk-synthetic-deepseek-key")
    db.init_db()
    builtins.register_builtin_tools()

    app = FastAPI()
    app.include_router(discord_api.router)
    app.include_router(discord_reminders.router)
    app.include_router(guild_api.router)
    return TestClient(app)


def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def test_parse_trigger_at_date_only_defaults_to_0900_jst():
    now = datetime(2026, 11, 20, 0, 0, tzinfo=timezone.utc)
    dt = discord_reminders.parse_trigger_at(trigger_at="2026-12-01", tz_name="Asia/Tokyo", now=now)
    # 2026-12-01 09:00:00+09:00 == 2026-12-01 00:00:00+00:00
    assert dt == datetime(2026, 12, 1, 0, 0, tzinfo=timezone.utc)


def test_parse_trigger_at_rejects_past_time():
    now = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        discord_reminders.parse_trigger_at(trigger_at="2026-11-20T10:00:00+09:00", tz_name="Asia/Tokyo", now=now)


def test_owner_tools_only_available_in_discord_threads(env):
    schema_create = tools.openai_tools_schema()
    target_schema = next(s for s in schema_create if s["function"]["name"] == "create_discord_reminder")
    setup = {"connected": [], "secrets": {}}

    with request_context.bind(request_id="req1", session_id="web:main", is_admin=True):
        assert brain_catalog.available(target_schema, local_only=False, setup=setup) is False

    with request_context.bind(
        request_id="req2",
        session_id=f"discord:{CHANNEL_ID}",
        is_admin=True,
        discord_author_id=OWNER,
        discord_guild_id="2002",
    ):
        assert brain_catalog.available(target_schema, local_only=False, setup=setup) is True


def test_owner_create_list_cancel_and_claim_report(env):
    # Created in discord channel -> stored in discord_reminders, NOT personal reminders
    with request_context.bind(
        request_id="discord:10",
        session_id=f"discord:{CHANNEL_ID}",
        is_admin=True,
        discord_author_id=OWNER,
        discord_guild_id="2002",
    ):
        res1 = discord_reminder_tools.create_discord_reminder(
            title="定例MTG",
            trigger_at="2099-12-01",
            mention_target="everyone",
        )
        assert res1["created"] is True
        assert res1["reminder"]["channel_id"] == CHANNEL_ID
        assert res1["reminder"]["mention_target"] == "everyone"
        assert res1["reminder"]["trigger_at"] == "2099-12-01T00:00:00+00:00"

        res2 = discord_reminder_tools.create_discord_reminder(
            title="提出確認",
            delay_minutes=30,
        )
        assert res2["created"] is True
        assert res2["reminder"]["mention_target"] == "user"
        assert res2["reminder"]["author_id"] == OWNER

        listed = discord_reminder_tools.list_discord_reminders()
        assert listed["count"] == 2

        cancelled = discord_reminder_tools.cancel_discord_reminder(res2["reminder"]["id"])
        assert cancelled["cancelled"] is True
        assert cancelled["reminder"]["status"] == "cancelled"

    # Personal reminders table remains empty
    assert reminders.list_reminders(scope="all")["items"] == []

    # Claim due reminders at 2099-12-01T00:01:00Z
    future_now = datetime(2099, 12, 1, 0, 1, tzinfo=timezone.utc)
    claimed = discord_reminders.claim_due_reminders(now=future_now)
    assert len(claimed) == 1
    assert claimed[0]["scope"] == "owner"
    assert claimed[0]["title"] == "定例MTG"
    assert claimed[0]["mention_target"] == "everyone"

    # Second claim returns empty (already claimed)
    assert discord_reminders.claim_due_reminders(now=future_now) == []

    # Report sent via API
    report_resp = env.post(
        f"/api/channels/discord/reminders/owner/{claimed[0]['reminder_id']}",
        json={"status": "sent"},
        headers=auth_headers(),
    )
    assert report_resp.status_code == 200
    assert report_resp.json()["status"] == "sent"


def test_guild_mode_reminder_flow_and_isolation(env, monkeypatch):
    # Setup Guild A
    setup_resp = env.post(
        "/api/guild/setup",
        json={
            "guild_id": GUILD_A,
            "author_id": "9999",
            "manage_guild": True,
            "timezone": "Asia/Tokyo",
        },
        headers=auth_headers(),
    )
    assert setup_resp.status_code == 200

    calls = []

    def fake_chat_completion(messages, tools=None, **kwargs):
        calls.append({"messages": list(messages), "tools": tools})
        if len(calls) == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_r1",
                        "type": "function",
                        "function": {
                            "name": "create_discord_reminder",
                            "arguments": '{"title": "スプリント振り返り", "trigger_at": "2099-12-10"}',
                        },
                    }
                ],
            }
        return {"content": "2099-12-10 09:00にこのチャンネルへメンション付きでリマインドしますね！"}

    monkeypatch.setattr(lmstudio_client, "chat_completion", fake_chat_completion)

    resp = env.post(
        "/api/channels/discord/events",
        json={
            "event_id": "50001",
            "guild_id": GUILD_A,
            "channel_id": CHANNEL_ID,
            "author_id": MEMBER_A,
            "display_name": "アリス",
            "message": "12月10日にスプリント振り返りを通知して！",
        },
        headers=auth_headers(),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "guild"
    assert data["status"] == "completed"
    assert "2099-12-10" in data["reply"]

    # Owner app.db has 0 discord_reminders
    assert discord_reminders.list_owner_reminders() == []

    # Guild DB has 1 scheduled reminder with default mention_target='user'
    with guild_api._connect(GUILD_A) as conn:
        g_items = discord_reminders.list_guild_reminders(conn, channel_id=CHANNEL_ID)
    assert len(g_items) == 1
    assert g_items[0]["author_id"] == MEMBER_A
    assert g_items[0]["mention_target"] == "user"
    assert g_items[0]["trigger_at"] == "2099-12-10T00:00:00+00:00"

    # Member B cannot cancel Member A's reminder
    with guild_api._connect(GUILD_A) as conn:
        with pytest.raises(ValueError):
            discord_reminders.cancel_guild_reminder(conn, g_items[0]["id"], author_id=MEMBER_B)

    # Claim due reminders across Guild DBs
    due = discord_reminders.claim_due_reminders(now=datetime(2099, 12, 10, 1, 0, tzinfo=timezone.utc))
    assert len(due) == 1
    assert due[0]["scope"] == "guild"
    assert due[0]["guild_id"] == GUILD_A
    assert due[0]["channel_id"] == CHANNEL_ID

    # Report delivered
    rep = env.post(
        f"/api/channels/discord/reminders/guild/{due[0]['reminder_id']}",
        json={"status": "sent", "guild_id": GUILD_A},
        headers=auth_headers(),
    )
    assert rep.status_code == 200


def test_bot_deliver_reminders_mentions_and_failure_reporting():
    assert relay.reminder_text({"mention_target": "user", "author_id": "123", "title": "テスト", "message": "テスト"}) == "<@123>\n⏰ **テスト**"
    assert relay.reminder_text({"mention_target": "everyone", "author_id": "123", "title": "会議", "message": "資料準備"}) == "@everyone\n⏰ **会議**\n資料準備"

    sent_calls = []
    reports = []

    class FakeChannel:
        def __init__(self, should_fail: bool = False):
            self.should_fail = should_fail

        async def send(self, content: str, **kwargs):
            if self.should_fail:
                raise RuntimeError("Missing Access")
            sent_calls.append((content, kwargs))

    class FakeCore:
        async def claim_reminders(self):
            return {
                "reminders": [
                    {
                        "scope": "owner",
                        "guild_id": None,
                        "reminder_id": 1,
                        "channel_id": "111",
                        "author_id": "222",
                        "title": "本人宛",
                        "message": "本人宛",
                        "mention_target": "user",
                    },
                    {
                        "scope": "guild",
                        "guild_id": "8001",
                        "reminder_id": 2,
                        "channel_id": "333",
                        "author_id": "444",
                        "title": "全員宛",
                        "message": "全員宛",
                        "mention_target": "everyone",
                    },
                ]
            }

        async def report_reminder(self, scope, reminder_id, status, error=None, guild_id=None):
            reports.append((scope, reminder_id, status, error, guild_id))

    async def get_channel(cid: int):
        return FakeChannel(should_fail=(cid == 333))

    sent_count = asyncio.run(
        bot.deliver_reminders(
            FakeCore(),
            get_channel,
            allowed_mentions_for=lambda item: f"AM:{item['mention_target']}",
        )
    )
    assert sent_count == 1
    assert sent_calls == [("<@222>\n⏰ **本人宛**", {"allowed_mentions": "AM:user"})]
    assert reports == [
        ("owner", 1, "sent", None, None),
        ("guild", 2, "failed", "RuntimeError", "8001"),
    ]
