"""D1 Discord Owner mode: Core decides the owner; guests never reach the Brain (#397)."""
import asyncio
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.test_setup_integrations import isolated  # noqa: F401 - autouse isolation
from backend import conversation_api, discord_api
from backend.channels.discord import bot, relay

TOKEN = "t" * 40
OWNER, GUILD = "1001", "2002"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("PETIT_DISCORD_SERVICE_TOKEN", TOKEN)
    monkeypatch.setenv("PETIT_DISCORD_OWNER_ID", OWNER)
    monkeypatch.setenv("PETIT_DISCORD_OWNER_GUILD_IDS", GUILD + ", 3003")
    calls = []

    def fake_submit(thread_id, request_id, message, **kwargs):
        calls.append((thread_id, request_id, message, kwargs))
        return {"status": "completed", "reply": "返答: " + message}

    monkeypatch.setattr(conversation_api, "submit", fake_submit)
    app = FastAPI()
    app.include_router(discord_api.router)
    test = TestClient(app)
    test.calls = calls
    return test


def event(**overrides):
    body = {"event_id": "555", "channel_id": "777", "guild_id": None, "author_id": OWNER, "message": "明日の予定は？"}
    body.update(overrides)
    return body


def post(client, body, token=TOKEN):
    return client.post("/api/channels/discord/events", json=body, headers={"Authorization": "Bearer " + token})


def test_owner_dm_goes_to_core_thread_as_admin(client):
    data = post(client, event()).json()
    assert data == {"mode": "owner", "status": "completed", "reply": "返答: 明日の予定は？", "request_id": "discord:555"}
    thread_id, request_id, message, kwargs = client.calls[0]
    assert (thread_id, request_id) == ("discord:777", "discord:555")
    assert kwargs == {"source": "discord", "is_admin": True}


def test_owner_in_designated_guild_is_owner(client):
    assert post(client, event(guild_id="3003")).json()["mode"] == "owner"


@pytest.mark.parametrize("body", [event(author_id="9999"), event(author_id="9999", guild_id=GUILD), event(guild_id="4004")])
def test_guest_or_undesignated_guild_never_calls_brain(client, body):
    data = post(client, body).json()
    assert data["mode"] == "guest" and data["reply"] == discord_api.GUEST_GUIDE
    assert client.calls == []


def test_missing_owner_setting_treats_everyone_as_guest(client, monkeypatch):
    monkeypatch.delenv("PETIT_DISCORD_OWNER_ID")
    assert post(client, event()).json()["mode"] == "guest" and client.calls == []


def test_token_is_required(client, monkeypatch):
    assert post(client, event(), token="wrong").status_code == 401
    monkeypatch.setenv("PETIT_DISCORD_SERVICE_TOKEN", "short")
    assert post(client, event()).status_code == 503
    assert client.calls == []


def test_ids_must_be_discord_snowflakes(client):
    assert post(client, event(channel_id="../x")).status_code == 422


def test_waiting_approval_points_to_core_ui(client, monkeypatch):
    monkeypatch.setattr(conversation_api, "submit", lambda *a, **k: {"status": "waiting_approval", "reply": "保存しますか？"})
    assert discord_api.APPROVAL_NOTE in post(client, event()).json()["reply"]


def test_redelivered_event_reuses_saved_turn(monkeypatch):
    # Real Core ledger: same message ID → same request ID → no second Brain run.
    monkeypatch.setenv("PETIT_DISCORD_SERVICE_TOKEN", TOKEN)
    monkeypatch.setenv("PETIT_DISCORD_OWNER_ID", OWNER)
    runs = []
    monkeypatch.setattr(conversation_api.brain, "run", lambda request_id, **k: runs.append(request_id) or
                        conversation_api.store.finish(request_id, {"reply": "ok"}))
    app = FastAPI()
    app.include_router(discord_api.router)
    test = TestClient(app)
    first = post(test, event()).json()
    second = post(test, event()).json()
    assert first["reply"] == second["reply"] == "ok" and runs == ["discord:555"]


def incoming(**overrides):
    values = dict(event_id="1", channel_id="2", guild_id="3", author_id=OWNER, content="<@42> 進捗どう？",
                  author_is_bot=False, mentions_bot=True)
    values.update(overrides)
    return relay.Incoming(**values)


def test_extract_handles_dm_and_mentions_only():
    assert relay.extract(incoming(), "42") == "進捗どう？"
    assert relay.extract(incoming(content="<@!42>hi"), "42") == "hi"
    assert relay.extract(incoming(mentions_bot=False), "42") is None  # guild chatter is not read
    assert relay.extract(incoming(guild_id=None, mentions_bot=False, content="DM"), "42") == "DM"
    assert relay.extract(incoming(author_is_bot=True), "42") is None
    assert relay.extract(incoming(content="<@42>"), "42") is None


def test_split_respects_limit_and_keeps_all_text():
    text = ("段落A" * 300) + "\n\n" + ("行B" * 500) + "\n" + ("C" * 2500)
    chunks = relay.split(text)
    assert all(len(c) <= relay.LIMIT for c in chunks) and len(chunks) >= 3
    assert "".join(chunks).replace("\n", "") == text.replace("\n", "")
    assert relay.split("  ") == []


def test_core_client_sends_token_and_degrades_when_core_is_down():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json={"reply": "やあ"})

    async def run(transport):
        core = bot.CoreClient("http://core", TOKEN, transport=transport)
        try:
            return await core.relay({"x": 1})
        finally:
            await core.close()

    assert asyncio.run(run(httpx.MockTransport(handler))) == "やあ" and seen["auth"] == "Bearer " + TOKEN
    down = httpx.MockTransport(lambda request: (_ for _ in ()).throw(httpx.ConnectError("down")))
    assert asyncio.run(run(down)) == bot.UNAVAILABLE
