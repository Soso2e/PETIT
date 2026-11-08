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
    assert data == {"mode": "owner", "status": "completed", "reply": "返答: 明日の予定は？", "request_id": "discord:555",
                    "approvals": []}
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

    assert asyncio.run(run(httpx.MockTransport(handler)))["reply"] == "やあ" and seen["auth"] == "Bearer " + TOKEN
    down = httpx.MockTransport(lambda request: (_ for _ in ()).throw(httpx.ConnectError("down")))
    assert asyncio.run(run(down))["reply"] == bot.UNAVAILABLE


# --- D2: approval buttons and notifications -------------------------------------------

def test_button_ids_round_trip_and_reject_foreign_ids():
    assert relay.parse_button(relay.button_id("abc123", True)) == ("abc123", True)
    assert relay.parse_button(relay.button_id("abc123", False)) == ("abc123", False)
    for bad in (None, "other:approve:x", "petit:delete:x", "petit:approve:../x", "petit:approve"):
        assert relay.parse_button(bad) is None
    assert "```x```" not in relay.approval_text({"name": "n", "preview": "```x```"})


def _approval_turn(monkeypatch, request_id="discord:555"):
    from backend import conversation_store as store
    monkeypatch.setenv("PETIT_DISCORD_SERVICE_TOKEN", TOKEN)
    monkeypatch.setenv("PETIT_DISCORD_OWNER_ID", OWNER)
    monkeypatch.setenv("PETIT_DISCORD_OWNER_GUILD_IDS", GUILD)
    store.create_thread("discord:777", source="discord")
    store.accept("discord:777", request_id, {"message": "m", "is_admin": True})
    call = {"id": "c1", "function": {"name": "update_persona_file"}}
    approval_id = store.propose(request_id, call, {"file": "SOUL.md", "content": "# SOUL\n静かに。", "reason": "r"})
    store.finish(request_id, {"reply": "変えますか？"}, status="waiting_approval")
    app = FastAPI()
    app.include_router(discord_api.router)
    return TestClient(app), approval_id


def decision(approval_id, **overrides):
    body = {"interaction_id": "9", "approval_id": approval_id, "guild_id": None, "author_id": OWNER, "approved": True}
    body.update(overrides)
    return body


def test_waiting_turn_returns_core_preview_for_buttons(monkeypatch):
    test, approval_id = _approval_turn(monkeypatch)
    data = test.get("/api/channels/discord/events/555", headers={"Authorization": "Bearer " + TOKEN}).json()
    assert data["status"] == "waiting_approval"
    assert data["approvals"][0]["approval_id"] == approval_id and "+静かに。" in data["approvals"][0]["preview"]


@pytest.mark.parametrize("overrides", [{"author_id": "9999"}, {"guild_id": "4004"}])
def test_only_owner_in_owner_context_can_press(monkeypatch, overrides):
    test, approval_id = _approval_turn(monkeypatch)
    calls = []
    monkeypatch.setattr(conversation_api, "decide", lambda *a: calls.append(a))
    response = test.post("/api/channels/discord/approvals", json=decision(approval_id, **overrides),
                         headers={"Authorization": "Bearer " + TOKEN})
    assert response.status_code == 403 and calls == []


def test_owner_press_decides_discord_approval(monkeypatch):
    test, approval_id = _approval_turn(monkeypatch)
    calls = []
    monkeypatch.setattr(conversation_api, "decide",
                        lambda aid, approved: calls.append((aid, approved)) or {"status": "completed", "reply": "変えました"})
    data = test.post("/api/channels/discord/approvals", json=decision(approval_id, approved=False),
                     headers={"Authorization": "Bearer " + TOKEN}).json()
    assert calls == [(approval_id, False)] and data["reply"] == "変えました"


def test_web_approvals_cannot_be_decided_from_discord(monkeypatch):
    test, approval_id = _approval_turn(monkeypatch, request_id="web-request")
    response = test.post("/api/channels/discord/approvals", json=decision(approval_id),
                         headers={"Authorization": "Bearer " + TOKEN})
    assert response.status_code == 404


def _notify_setup(monkeypatch, enabled=True, categories=("schedule_reminder",)):
    from backend import notifications
    monkeypatch.setenv("PETIT_DISCORD_SERVICE_TOKEN", TOKEN)
    monkeypatch.setenv("PETIT_DISCORD_OWNER_ID", OWNER)
    if enabled:
        monkeypatch.setenv("PETIT_DISCORD_NOTIFICATIONS", "on")
    notifications.init_db()
    notifications.update_preferences({c: True for c in categories})
    app = FastAPI()
    app.include_router(discord_api.router)
    return TestClient(app), notifications


def test_notifications_are_claimed_once_and_respect_preferences(monkeypatch):
    test, notifications = _notify_setup(monkeypatch)
    on, _ = notifications._create_event("schedule_reminder", "10分後に会議", "定例", "/")
    notifications._create_event("high_task", "OFF のカテゴリ", "送らない", "/")
    headers = {"Authorization": "Bearer " + TOKEN}
    first = test.get("/api/channels/discord/notifications", headers=headers).json()
    assert first["owner_id"] == OWNER and [n["event_id"] for n in first["notifications"]] == [on]
    assert test.get("/api/channels/discord/notifications", headers=headers).json()["notifications"] == []
    assert test.post(f"/api/channels/discord/notifications/{on}", json={"status": "sent"}, headers=headers).status_code == 200
    assert test.post(f"/api/channels/discord/notifications/{on}", json={"status": "sent"}, headers=headers).status_code == 404


def test_notifications_off_without_opt_in(monkeypatch):
    test, notifications = _notify_setup(monkeypatch, enabled=False)
    notifications._create_event("schedule_reminder", "t", "b", "/")
    data = test.get("/api/channels/discord/notifications", headers={"Authorization": "Bearer " + TOKEN}).json()
    assert data == {"owner_id": None, "notifications": []}


def test_deliver_notifications_reports_each_outcome():
    reports = []

    class Core:
        async def claim_notifications(self):
            return {"owner_id": OWNER, "notifications": [{"event_id": 1, "title": "a", "body": "b"},
                                                          {"event_id": 2, "title": "c", "body": "d"}]}

        async def report(self, event_id, status, error=None):
            reports.append((event_id, status))

    class User:
        count = 0

        async def send(self, text):
            User.count += 1
            if User.count == 2:
                raise RuntimeError("dm closed")

    async def fetch_user(uid):
        assert uid == int(OWNER)
        return User()

    assert asyncio.run(bot.deliver_notifications(Core(), fetch_user)) == 1
    assert reports == [(1, "sent"), (2, "failed")]
