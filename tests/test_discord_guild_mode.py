"""D3 Discord Guild mode tests (#403).

Covers:
- Guild mode cannot reach owner Tool Registry, owner DB (app.db), PETIT Home, or CLI/Brain
- Unconfigured guild makes 0 DeepSeek calls
- /petit setup and /petit reset reject users without Manage Server permission
- Guild A data is completely invisible from Guild B (separate SQLite files under storage/guilds/<guild_id>.db)
- Daily server call/token limits and per-user rate limits block DeepSeek calls and reply "今日はここまで"
- /petit forget-me removes all profile and conversation records for that user
- DeepSeek API key and service token are never leaked in replies or errors
- /api/guild/* works via Bearer service token without admin cookie (TOKEN_AUTH_PREFIXES)
- Bot relay slash command parsing and dispatch
"""
from __future__ import annotations

import asyncio
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.test_setup_integrations import isolated  # noqa: F401 - autouse isolation
from backend import (
    brain_priority,
    config,
    conversation_api,
    db,
    discord_api,
    guild_api,
    lmstudio_client,
    petit_home,
    request_context,
    setup_api,
    tools,
)
from backend.channels.discord import bot, relay

TOKEN = "s" * 40
OWNER = "1001"
OWNER_GUILD = "2002"
GUILD_A = "8001"
GUILD_B = "8002"
ADMIN_USER = "9001"
MEMBER_USER = "9002"
OTHER_USER = "9003"


@pytest.fixture
def env( tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STORAGE_DIR", tmp_path / "storage")
    monkeypatch.setenv("PETIT_DISCORD_SERVICE_TOKEN", TOKEN)
    monkeypatch.setenv("PETIT_DISCORD_OWNER_ID", OWNER)
    monkeypatch.setenv("PETIT_DISCORD_OWNER_GUILD_IDS", OWNER_GUILD)
    monkeypatch.setenv("PETIT_DEEPSEEK_API_KEY", "sk-synthetic-deepseek-secret-key")
    deepseek_calls: list[dict] = []

    def fake_post_completion(*, url, payload, headers, route, target):
        deepseek_calls.append({"url": url, "payload": payload, "headers": headers, "route": route, "target": target})
        user_msgs = [m["content"] for m in payload["messages"] if m["role"] == "user"]
        last = user_msgs[-1] if user_msgs else ""
        return {
            "choices": [{"message": {"role": "assistant", "content": f"Guild返答: {last}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
        }

    monkeypatch.setattr(lmstudio_client, "_post_completion", fake_post_completion)
    app = FastAPI()
    app.include_router(setup_api.router)
    setup_api.install(app)
    app.include_router(discord_api.router)
    app.include_router(guild_api.router)
    client = TestClient(app, base_url="http://localhost")
    client.deepseek_calls = deepseek_calls
    return client


def auth_headers(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def setup_guild(client: TestClient, guild_id: str = GUILD_A, **overrides):
    body = {
        "interaction_id": "10",
        "guild_id": guild_id,
        "author_id": ADMIN_USER,
        "manage_guild": True,
        "timezone": "Asia/Tokyo",
        "daily_call_limit": 50,
        "daily_token_limit": 60000,
        "user_hourly_limit": 15,
    }
    body.update(overrides)
    return client.post("/api/guild/setup", json=body, headers=auth_headers())


def mention_event(guild_id: str = GUILD_A, author_id: str = MEMBER_USER, message: str = "こんにちは", **overrides):
    body = {
        "event_id": "500",
        "channel_id": "700",
        "guild_id": guild_id,
        "author_id": author_id,
        "display_name": "アリス",
        "message": message,
    }
    body.update(overrides)
    return body


def test_guild_mode_cannot_reach_owner_tools_db_home_or_cli(env):
    """In Guild mode, any attempt to touch owner DB, Tool Registry, PETIT Home, or Brain/CLI raises GuildIsolationError."""
    setup_guild(env, GUILD_A)

    with request_context.guild_mode(guild_id=GUILD_A):
        # Owner SQLite (storage/app.db)
        with pytest.raises(request_context.GuildIsolationError):
            db.get_connection()
        with pytest.raises(request_context.GuildIsolationError):
            with db.write_transaction():
                pass

        # Owner Tool Registry
        with pytest.raises(request_context.GuildIsolationError):
            tools.openai_tools_schema()
        with pytest.raises(request_context.GuildIsolationError):
            tools.dispatch("get_tasks", {})

        # PETIT Home
        with pytest.raises(request_context.GuildIsolationError):
            petit_home.root()
        with pytest.raises(request_context.GuildIsolationError):
            petit_home.ensure()
        with pytest.raises(request_context.GuildIsolationError):
            petit_home.persona()

        # Owner Brain / CLI selection & Core Turn
        for provider in ("antigravity_cli", "codex", "claude_code", "deepseek"):
            with pytest.raises(request_context.GuildIsolationError):
                brain_priority.target(provider)
        with pytest.raises(request_context.GuildIsolationError):
            brain_priority.run("req-1", lambda *a, **k: {})
        with pytest.raises(request_context.GuildIsolationError):
            conversation_api.submit("t1", "r1", "hello")
        with pytest.raises(request_context.GuildIsolationError):
            conversation_api.process("r1")


def test_guild_mention_uses_only_deepseek_without_tools_and_never_touches_app_db(env, monkeypatch):
    """Configured guild mention calls DeepSeek with tools=None and writes only to storage/guilds/<guild_id>.db."""
    owner_submit_calls = []
    monkeypatch.setattr(conversation_api, "submit", lambda *a, **k: owner_submit_calls.append((a, k)))

    assert setup_guild(env, GUILD_A).status_code == 200
    guild_db = config.STORAGE_DIR / "guilds" / f"{GUILD_A}.db"
    assert guild_db.is_file()

    resp = env.post("/api/channels/discord/events", json=mention_event(), headers=auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "guild"
    assert data["status"] == "completed"
    assert "こんにちは" in data["reply"]
    assert owner_submit_calls == []

    # DeepSeek was called once, with no tools
    assert len(env.deepseek_calls) == 1
    call = env.deepseek_calls[0]
    assert call["target"]["provider"] == "deepseek"
    assert "tools" not in call["payload"]

    # Owner app.db has 0 guild conversations
    with db.get_connection() as conn:
        rows = conn.execute("SELECT * FROM conversations").fetchall()
    assert rows == []


def test_unconfigured_guild_calls_deepseek_zero_times(env):
    """Unconfigured guild returns GUEST_GUIDE and never calls DeepSeek."""
    resp = env.post("/api/channels/discord/events", json=mention_event(guild_id="999999"), headers=auth_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "guest"
    assert data["reply"] == discord_api.GUEST_GUIDE
    assert env.deepseek_calls == []

    # Direct /api/guild/messages on unconfigured guild also makes 0 DeepSeek calls
    resp2 = env.post("/api/guild/messages", json=mention_event(guild_id="999999"), headers=auth_headers())
    assert resp2.status_code == 200
    assert resp2.json()["mode"] == "guest"
    assert env.deepseek_calls == []


def test_setup_and_reset_require_manage_server_permission(env):
    """Users without Manage Server (manage_guild=False and bit 0x20 unset) are rejected with 403."""
    denied_setup = env.post(
        "/api/guild/setup",
        json={"interaction_id": "1", "guild_id": GUILD_A, "author_id": MEMBER_USER, "manage_guild": False, "permissions": 0},
        headers=auth_headers(),
    )
    assert denied_setup.status_code == 403
    assert not guild_api.is_configured(GUILD_A)

    # Bitfield permission (0x20 = MANAGE_GUILD) allows setup even if manage_guild bool is False
    allowed_setup = env.post(
        "/api/guild/setup",
        json={"interaction_id": "2", "guild_id": GUILD_A, "author_id": ADMIN_USER, "manage_guild": False, "permissions": 0x20},
        headers=auth_headers(),
    )
    assert allowed_setup.status_code == 200
    assert guild_api.is_configured(GUILD_A)

    # Non-admin cannot reset
    denied_reset = env.post(
        "/api/guild/reset",
        json={"interaction_id": "3", "guild_id": GUILD_A, "author_id": MEMBER_USER, "manage_guild": False, "permissions": 0x08},
        headers=auth_headers(),
    )
    assert denied_reset.status_code == 403
    assert guild_api.is_configured(GUILD_A)

    # Admin with manage_guild can reset and delete the DB file
    allowed_reset = env.post(
        "/api/guild/reset",
        json={"interaction_id": "4", "guild_id": GUILD_A, "author_id": ADMIN_USER, "manage_guild": True},
        headers=auth_headers(),
    )
    assert allowed_reset.status_code == 200
    assert not guild_api.is_configured(GUILD_A)
    assert not (config.STORAGE_DIR / "guilds" / f"{GUILD_A}.db").exists()
    assert env.deepseek_calls == []


def test_guild_a_data_is_invisible_from_guild_b(env):
    """Guild A and Guild B use separate SQLite files; conversations and profiles never cross."""
    setup_guild(env, GUILD_A)
    setup_guild(env, GUILD_B)

    env.post(
        "/api/guild/me",
        json={"interaction_id": "10", "guild_id": GUILD_A, "author_id": MEMBER_USER,
              "display_name": "アリスA", "role_note": "サーバーAの会計", "memo": "秘密プロジェクトA"},
        headers=auth_headers(),
    )
    env.post(
        "/api/channels/discord/events",
        json=mention_event(guild_id=GUILD_A, event_id="601", message="合言葉はリンゴです"),
        headers=auth_headers(),
    )

    # Same user checks /petit me in Guild B -> nothing recorded
    me_b = env.post(
        "/api/guild/me",
        json={"interaction_id": "11", "guild_id": GUILD_B, "author_id": MEMBER_USER},
        headers=auth_headers(),
    ).json()
    assert me_b["profile"] is None
    assert me_b["conversation_count"] == 0
    assert "何も記録していません" in me_b["reply"]

    # Mention in Guild B does not include Guild A's member info or conversation in DeepSeek prompt
    env.deepseek_calls.clear()
    env.post(
        "/api/channels/discord/events",
        json=mention_event(guild_id=GUILD_B, event_id="602", author_id=OTHER_USER, display_name="ボブ", message="誰がいる？"),
        headers=auth_headers(),
    )
    assert len(env.deepseek_calls) == 1
    sent_text = str(env.deepseek_calls[0]["payload"]["messages"])
    assert "アリスA" not in sent_text
    assert "サーバーAの会計" not in sent_text
    assert "秘密プロジェクトA" not in sent_text
    assert "合言葉はリンゴです" not in sent_text


def test_daily_budget_and_user_rate_limit_stop_before_deepseek(env):
    """Exceeding daily call limit, daily token limit, or user hourly limit returns '今日はここまで' without calling DeepSeek."""
    # 1. Server daily call limit = 2
    setup_guild(env, GUILD_A, daily_call_limit=2, daily_token_limit=60000, user_hourly_limit=10)
    r1 = env.post("/api/channels/discord/events", json=mention_event(event_id="701", message="1回目"), headers=auth_headers()).json()
    r2 = env.post("/api/channels/discord/events", json=mention_event(event_id="702", message="2回目"), headers=auth_headers()).json()
    assert r1["status"] == "completed" and r2["status"] == "completed"
    assert len(env.deepseek_calls) == 2

    r3 = env.post("/api/channels/discord/events", json=mention_event(event_id="703", message="3回目"), headers=auth_headers()).json()
    assert r3["status"] == "budget_exceeded"
    assert "今日はここまで" in r3["reply"]
    assert len(env.deepseek_calls) == 2  # DeepSeek not called

    # 2. Server daily token limit exceeded (2 calls * 30 tokens = 60 tokens already used; set token limit = 60, call limit = 10)
    setup_guild(env, GUILD_A, daily_call_limit=10, daily_token_limit=60, user_hourly_limit=10)
    r4 = env.post("/api/channels/discord/events", json=mention_event(event_id="704", message="トークン超過"), headers=auth_headers()).json()
    assert r4["status"] == "budget_exceeded"
    assert "今日はここまで" in r4["reply"]
    assert len(env.deepseek_calls) == 2

    # 3. Per-user hourly rate limit (raise server limits, set user_hourly_limit = 2; MEMBER_USER has 2 calls, OTHER_USER has 0)
    setup_guild(env, GUILD_A, daily_call_limit=100, daily_token_limit=60000, user_hourly_limit=2)
    r5 = env.post(
        "/api/channels/discord/events",
        json=mention_event(event_id="705", author_id=MEMBER_USER, message="ユーザー上限"),
        headers=auth_headers(),
    ).json()
    assert r5["status"] == "rate_limited"
    assert "今日はここまで" in r5["reply"]
    assert len(env.deepseek_calls) == 2

    # Another user in the same guild can still talk
    r6 = env.post(
        "/api/channels/discord/events",
        json=mention_event(event_id="706", author_id=OTHER_USER, display_name="別メンバー", message="別ユーザーは話せる"),
        headers=auth_headers(),
    ).json()
    assert r6["status"] == "completed"
    assert len(env.deepseek_calls) == 3


def test_forget_me_erases_all_user_records(env):
    """After /petit forget-me, neither profile nor conversation history remains for that user in the guild DB."""
    setup_guild(env, GUILD_A)
    env.post(
        "/api/guild/me",
        json={"interaction_id": "20", "guild_id": GUILD_A, "author_id": MEMBER_USER,
              "display_name": "アリス", "role_note": "デザイン担当", "memo": "火曜休み"},
        headers=auth_headers(),
    )
    env.post(
        "/api/channels/discord/events",
        json=mention_event(event_id="801", author_id=MEMBER_USER, message="デザインの件よろしく"),
        headers=auth_headers(),
    )

    before = env.post(
        "/api/guild/me",
        json={"interaction_id": "21", "guild_id": GUILD_A, "author_id": MEMBER_USER},
        headers=auth_headers(),
    ).json()
    assert before["profile"]["role_note"] == "デザイン担当"
    assert before["conversation_count"] == 1

    forgotten = env.post(
        "/api/guild/forget-me",
        json={"interaction_id": "22", "guild_id": GUILD_A, "author_id": MEMBER_USER},
        headers=auth_headers(),
    ).json()
    assert forgotten["status"] == "completed"
    assert forgotten["deleted"] is True

    after = env.post(
        "/api/guild/me",
        json={"interaction_id": "23", "guild_id": GUILD_A, "author_id": MEMBER_USER},
        headers=auth_headers(),
    ).json()
    assert after["profile"] is None
    assert after["conversation_count"] == 0
    assert "何も記録していません" in after["reply"]

    # Subsequent conversation in the same channel does not include forgotten user's text or profile
    env.deepseek_calls.clear()
    env.post(
        "/api/channels/discord/events",
        json=mention_event(event_id="802", author_id=OTHER_USER, display_name="ボブ", message="今の状況は？"),
        headers=auth_headers(),
    )
    prompt_dump = str(env.deepseek_calls[0]["payload"]["messages"])
    assert "デザイン担当" not in prompt_dump
    assert "火曜休み" not in prompt_dump
    assert "デザインの件よろしく" not in prompt_dump


def test_secrets_are_never_exposed_in_guild_replies(env, monkeypatch):
    """If DeepSeek error or reply accidentally echoes the API key, it is redacted before returning."""
    setup_guild(env, GUILD_A)
    secret_key = "sk-synthetic-deepseek-secret-key"

    def leaking_error(*, url, payload, headers, route, target):
        raise lmstudio_client.LMStudioError(f"upstream failed with key {secret_key} and token {TOKEN}")

    monkeypatch.setattr(lmstudio_client, "_post_completion", leaking_error)
    resp = env.post("/api/channels/discord/events", json=mention_event(event_id="901"), headers=auth_headers()).json()
    assert resp["status"] == "failed"
    assert secret_key not in resp["reply"]
    assert TOKEN not in resp["reply"]
    assert "[REDACTED]" in resp["reply"]


def test_slash_command_parsing_and_bot_dispatch(env):
    """Bot slash helper parses /petit subcommands and relays them to Core /api/guild/*."""
    assert "/api/guild/" in setup_api.TOKEN_AUTH_PREFIXES

    setup_data = {"name": "petit", "options": [{"name": "setup", "options": [{"name": "daily_call_limit", "value": 25}]}]}
    assert relay.parse_slash(setup_data) == ("setup", {"daily_call_limit": 25})
    assert relay.parse_slash({"name": "other"}) is None
    assert relay.parse_slash({"name": "petit", "options": [{"name": "unknown"}]}) is None

    def handler(request: httpx.Request) -> httpx.Response:
        res = env.request(
            request.method,
            request.url.path,
            content=request.content,
            headers=dict(request.headers),
        )
        return httpx.Response(res.status_code, json=res.json())

    async def run_flow():
        core = bot.CoreClient("http://localhost", TOKEN, transport=httpx.MockTransport(handler))
        try:
            # DM slash command is rejected politely
            dm_reply = await bot.dispatch_slash_interaction(
                core, interaction_id="1", guild_id=None, author_id=MEMBER_USER,
                display_name="アリス", manage_guild=False, permissions=0, data=setup_data,
            )
            # Non-admin setup is rejected
            denied = await bot.dispatch_slash_interaction(
                core, interaction_id="2", guild_id=GUILD_A, author_id=MEMBER_USER,
                display_name="アリス", manage_guild=False, permissions=0, data=setup_data,
            )
            # Admin setup succeeds
            ok = await bot.dispatch_slash_interaction(
                core, interaction_id="3", guild_id=GUILD_A, author_id=ADMIN_USER,
                display_name="管理者", manage_guild=True, permissions=0x20, data=setup_data,
            )
            # /petit me and /petit forget-me
            me_reply = await bot.dispatch_slash_interaction(
                core, interaction_id="4", guild_id=GUILD_A, author_id=MEMBER_USER,
                display_name="アリス", manage_guild=False, permissions=0,
                data={"name": "petit", "options": [{"name": "me", "options": [{"name": "role_note", "value": "進行役"}]}]},
            )
            forget_reply = await bot.dispatch_slash_interaction(
                core, interaction_id="5", guild_id=GUILD_A, author_id=MEMBER_USER,
                display_name="アリス", manage_guild=False, permissions=0,
                data={"name": "petit", "options": [{"name": "forget-me"}]},
            )
            return dm_reply, denied, ok, me_reply, forget_reply
        finally:
            await core.close()

    dm_reply, denied, ok, me_reply, forget_reply = asyncio.run(run_flow())
    assert "サーバー内でのみ" in dm_reply
    assert "権限が必要です" in denied
    assert "Guild モードを有効にしました" in ok
    assert "進行役" in me_reply
    assert "すべて消去しました" in forget_reply
