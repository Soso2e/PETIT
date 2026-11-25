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
    assert kwargs == {
        "source": "discord",
        "is_admin": True,
        "discord_author_id": "1001",
        "discord_guild_id": None,
    }


def test_owner_in_designated_guild_is_owner(client):
    assert post(client, event(guild_id="3003")).json()["mode"] == "owner"


@pytest.mark.parametrize("body", [event(author_id="9999"), event(author_id="9999", guild_id=GUILD), event(guild_id="4004")])
def test_guest_or_undesignated_guild_never_calls_brain(client, monkeypatch, body):
    monkeypatch.setenv("PETIT_DISCORD_GUILD_MODE", "on")
    data = post(client, body).json()
    assert data["mode"] == "guest" and data["reply"] == discord_api.GUEST_GUIDE
    assert client.calls == []


@pytest.mark.parametrize("body", [event(author_id="9999"), event(author_id="9999", guild_id=GUILD), event(guild_id="4004")])
def test_owner_only_by_default_guests_get_silence(client, body):
    data = post(client, body).json()
    assert data["mode"] == "guest" and data["reply"] == "" and data["status"] == "ignored"
    assert client.calls == []
    assert relay.split(data["reply"]) == []  # the Bot sends nothing


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


@pytest.mark.parametrize("content", [
    "ぷて、今日の予定は？",
    "ぷてぃ",
    "おーいペティット！",
    "PETITおはよう",
    "Hey petit, what's next?",
])
def test_extract_handles_wake_words_in_guild(content):
    assert relay.extract(incoming(mentions_bot=False, content=content), "42") == content


@pytest.mark.parametrize("content", [
    "appetite is good",
    "sign the petition",
    "普通の雑談",
])
def test_extract_ignores_non_wake_words_in_guild(content):
    assert relay.extract(incoming(mentions_bot=False, content=content), "42") is None


def test_extract_ignores_bot_even_with_wake_word():
    assert relay.extract(incoming(author_is_bot=True, mentions_bot=False, content="ぷてぃ"), "42") is None


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


def test_admin_registration_and_owner_routing(client, monkeypatch):
    submitted = []
    monkeypatch.setattr(
        conversation_api,
        "submit",
        lambda tid, rid, msg, **kw: submitted.append((tid, rid, msg, kw))
        or {"status": "completed", "reply": "管理者として実行しました"},
    )
    headers = {"Authorization": "Bearer " + TOKEN}
    new_admin = "777777777"

    # Non-owner cannot register admins
    r_forbid = client.post(
        "/api/channels/discord/admins",
        json={"action": "add", "actor_id": new_admin, "target_user_id": new_admin},
        headers=headers,
    )
    assert r_forbid.status_code == 200
    assert r_forbid.json()["status"] == "forbidden"

    # Before registration, user in guild is not owner
    r_before = client.post(
        "/api/channels/discord/events",
        json={"event_id": "201", "channel_id": "301", "guild_id": "999", "author_id": new_admin, "message": "pcみて"},
        headers=headers,
    )
    assert r_before.json()["mode"] == "guest"
    assert submitted == []

    # Initial owner adds user via mention format
    r_add = client.post(
        "/api/channels/discord/admins",
        json={"action": "add", "actor_id": OWNER, "target_user_id": f"<@{new_admin}>"},
        headers=headers,
    )
    assert r_add.status_code == 200
    assert "登録しました" in r_add.json()["reply"]

    # Registered admin gets owner mode (full Core tools) in any guild
    r_after = client.post(
        "/api/channels/discord/events",
        json={"event_id": "202", "channel_id": "301", "guild_id": "999", "author_id": new_admin, "message": "pcみて"},
        headers=headers,
    )
    assert r_after.status_code == 200
    assert r_after.json()["mode"] == "owner"
    assert r_after.json()["reply"] == "管理者として実行しました"
    assert submitted and submitted[0][3]["is_admin"] is True

    # List and remove
    r_list = client.post(
        "/api/channels/discord/admins",
        json={"action": "list", "actor_id": OWNER},
        headers=headers,
    )
    assert new_admin in r_list.json()["reply"]
    r_rem = client.post(
        "/api/channels/discord/admins",
        json={"action": "remove", "actor_id": OWNER, "target_user_id": new_admin},
        headers=headers,
    )
    assert "解除しました" in r_rem.json()["reply"]


def test_slash_admin_dispatch():
    sent = []

    class FakeCore:
        async def admin_command(self, body):
            sent.append(body)
            return {"reply": "ok"}

    reply = asyncio.run(
        bot.dispatch_slash_interaction(
            FakeCore(),
            interaction_id="100",
            guild_id="999",
            author_id=OWNER,
            display_name="soso",
            manage_guild=True,
            permissions=None,
            data={"name": "petit", "options": [{"name": "admin", "options": [{"name": "action", "value": "add"}, {"name": "user", "value": "555"}]}]},
        )
    )
    assert reply == "ok"
    assert sent == [{"action": "add", "actor_id": OWNER, "target_user_id": "555"}]


def test_archive_init_sync_and_schedule_dispatch():
    from types import SimpleNamespace
    from backend.channels.discord.bot import dispatch_slash_interaction

    calls = []
    scheduled = []

    class FakeCore:
        async def archive_set_sync_config(self, body):
            calls.append(("sync_config", body))
            return {"status": "ok", "enabled": body["enabled"], "sync_time": body["sync_time"]}

        async def archive_allowlist(self, guild_id=None, zone=None):
            return {"allow_guilds": {guild_id: {"channels": ["10", "20"]}}}

        async def archive_sync_config(self, guild_id=None):
            return {"config": {"enabled": True, "sync_time": "05:30"}}

    def fake_schedule(guild, **kwargs):
        scheduled.append((guild, kwargs))
        return True

    fake_guild = SimpleNamespace(id="999")

    # init
    reply = asyncio.run(
        dispatch_slash_interaction(
            FakeCore(),
            interaction_id="101",
            guild_id="999",
            author_id=OWNER,
            display_name="soso",
            manage_guild=True,
            permissions=None,
            data={"name": "petit", "options": [{"name": "archive", "options": [{"name": "action", "value": "init"}, {"name": "time", "value": "05:30"}]}]},
            guild=fake_guild,
            schedule_sync=fake_schedule,
        )
    )
    assert "全チャンネル" in reply
    assert "05:30" in reply
    assert calls[0][0] == "sync_config"
    assert scheduled[0][1]["register_all"] is True

    # list
    reply_list = asyncio.run(
        dispatch_slash_interaction(
            FakeCore(),
            interaction_id="102",
            guild_id="999",
            author_id=OWNER,
            display_name="soso",
            manage_guild=True,
            permissions=None,
            data={"name": "petit", "options": [{"name": "archive", "options": [{"name": "action", "value": "list"}]}]},
        )
    )
    assert "保存対象チャンネル（2件）" in reply_list
    assert "毎日 05:30" in reply_list


def test_sync_guild_archive_registers_and_checkpoints():
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from backend.channels.discord.bot import sync_guild_archive

    class FakeAuthor:
        def __init__(self, uid, name, bot=False):
            self.id = uid
            self.name = name
            self.display_name = name
            self.bot = bot

    class FakeMsg:
        def __init__(self, mid, ch, author, content, created_at):
            self.id = mid
            self.channel = ch
            self.guild = ch.guild
            self.author = author
            self.content = content
            self.created_at = created_at
            self.edited_at = None
            self.reference = None
            self.attachments = []

    class FakeChannel:
        def __init__(self, cid, name, guild, messages, parent_id=None, private=False, readable=True):
            self.id = cid
            self.name = name
            self.guild = guild
            self.parent_id = parent_id
            self.parent = None
            self._messages = messages
            self._private = private
            self._readable = readable

        def is_private(self):
            return self._private

        def permissions_for(self, member):
            return SimpleNamespace(view_channel=self._readable, read_message_history=self._readable)

        async def history(self, limit=None, after=None, before=None, oldest_first=True):
            for m in self._messages:
                if after and m.created_at <= after:
                    continue
                yield m

    class FakeGuild:
        def __init__(self):
            self.id = "999"
            self.name = "MyServer"
            self.me = object()
            self.text_channels = []
            self.forums = []
            self.threads = []

    guild = FakeGuild()
    t1 = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
    ch1 = FakeChannel("10", "general", guild, [])
    ch1._messages = [FakeMsg("1001", ch1, FakeAuthor("111", "soso"), "hello", t1)]
    ch_secret = FakeChannel("20", "secret", guild, [], readable=False)
    th_priv = FakeChannel("30", "priv-thread", guild, [], parent_id="10", private=True)
    guild.text_channels = [ch1, ch_secret]
    guild.threads = [th_priv]

    registered = []
    batches = []
    checkpoints = {}

    class FakeCore:
        async def archive_register(self, body):
            registered.append(body)
            return {"status": "ok"}

        async def archive_checkpoints(self, guild_id=None):
            return {"checkpoints": dict(checkpoints)}

        async def archive_events_batch(self, events):
            batches.extend(events)
            return {"status": "ok", "saved": len(events)}

        async def archive_set_checkpoint(self, body):
            checkpoints[body["channel_id"]] = body["completed_at"]
            return {"status": "ok"}

        async def archive_allowlist(self, guild_id=None, zone=None):
            return {"allow_guilds": {"999": {"channels": ["10"]}}}

    core = FakeCore()
    summary = asyncio.run(sync_guild_archive(core, guild, register_all=True, author_id="111", manage_guild=True))
    assert registered[0]["channel_ids"] == ["10"]  # secret and private thread excluded
    assert summary["channels"] == 1
    assert summary["saved"] == 1
    assert "10" in checkpoints

    # 2nd run uses checkpoint and finds no new messages
    summary2 = asyncio.run(sync_guild_archive(core, guild, register_all=False, author_id="111"))
    assert summary2["fetched"] == 0


def test_format_channel_context_and_payload():
    from backend.channels.discord.relay import (
        ContextMessage,
        Incoming,
        format_channel_context,
        payload,
    )

    recent = [
        ContextMessage(author_name="So", content="管理者の追加どうやってやるんだっけ？", message_id="101"),
        ContextMessage(author_name="PETIT", content="", is_bot=True, message_id="102"),
    ]
    reply_to = ContextMessage(author_name="So", content="パス教えて", message_id="99")

    ctx = format_channel_context(recent, reply_to)
    assert "返信先メッセージ:\n- So: パス教えて" in ctx
    assert "直近のチャンネル発言（古い順）:\n- So: 管理者の追加どうやってやるんだっけ？" in ctx
    assert "- PETIT:" not in ctx

    inc = Incoming("200", "300", "400", "500", "ぷて", False, False, display_name="So")
    body_with_ctx = payload(inc, "ぷて", channel_context=ctx)
    assert body_with_ctx["channel_context"] == ctx
    body_no_ctx = payload(inc, "ぷて")
    assert "channel_context" not in body_no_ctx

    # Older messages are trimmed first while preserving reply_to when exceeding max_chars
    many = [ContextMessage(author_name="So", content=f"msg-{i} " + ("x" * 120)) for i in range(10)]
    clipped = format_channel_context(many, reply_to, max_chars=550)
    assert "返信先メッセージ:\n- So: パス教えて" in clipped
    assert "msg-9" in clipped
    assert "msg-0" not in clipped


def test_fetch_channel_context_collects_history_and_reply():
    from types import SimpleNamespace
    from backend.channels.discord.bot import fetch_channel_context

    class FakeChannel:
        def __init__(self, history_msgs, fetched_reply=None):
            self._history_msgs = history_msgs
            self._fetched_reply = fetched_reply

        async def history(self, limit=10, before=None):
            # discord.py yields newest-first
            for item in self._history_msgs[:limit]:
                yield item

        async def fetch_message(self, message_id):
            if isinstance(self._fetched_reply, Exception):
                raise self._fetched_reply
            return self._fetched_reply

    so = SimpleNamespace(display_name="So", name="so", bot=False)
    petit = SimpleNamespace(display_name="PETIT", name="petit", bot=True)
    m_prev1 = SimpleNamespace(id="10", author=so, content="古い発言", attachments=[])
    m_prev2 = SimpleNamespace(id="11", author=petit, content="前回の返答", attachments=[])
    m_prev3 = SimpleNamespace(id="12", author=so, content="管理者の追加どうやってやるんだっけ？", attachments=[])
    ref_msg = SimpleNamespace(id="5", author=so, content="リプライ元の質問", attachments=[])

    # 1. Resolved reference + newest-first history -> reversed to chronological
    ch1 = FakeChannel([m_prev3, m_prev2, m_prev1])
    msg1 = SimpleNamespace(
        id="13",
        channel=ch1,
        reference=SimpleNamespace(message_id="5", resolved=ref_msg),
    )
    ctx1 = asyncio.run(fetch_channel_context(msg1))
    assert "返信先メッセージ:\n- So: リプライ元の質問" in ctx1
    idx1 = ctx1.index("- So: 古い発言")
    idx2 = ctx1.index("- PETIT: 前回の返答")
    idx3 = ctx1.index("- So: 管理者の追加どうやってやるんだっけ？")
    assert idx1 < idx2 < idx3

    # 2. Unresolved reference falls back to fetch_message; errors degrade safely
    ch2 = FakeChannel([m_prev3], fetched_reply=RuntimeError("forbidden"))
    msg2 = SimpleNamespace(
        id="14",
        channel=ch2,
        reference=SimpleNamespace(message_id="5", resolved=None),
    )
    ctx2 = asyncio.run(fetch_channel_context(msg2))
    assert "返信先メッセージ" not in ctx2
    assert "- So: 管理者の追加どうやってやるんだっけ？" in ctx2


def test_discord_event_passes_channel_context_to_brain_without_polluting_history(monkeypatch):
    from fastapi.testclient import TestClient
    from backend import brain, conversation_store, main

    monkeypatch.setenv("PETIT_DISCORD_SERVICE_TOKEN", TOKEN)
    monkeypatch.setenv("PETIT_DISCORD_OWNER_ID", OWNER)
    monkeypatch.setenv("PETIT_DISCORD_OWNER_GUILD_IDS", GUILD)

    captured_messages = []
    monkeypatch.setattr(brain, "check_provider", lambda thread: {"provider": "lmstudio", "model": "test"})

    def fake_chat_completion(messages, **kwargs):
        captured_messages.append(list(messages))
        return {"content": "管理者の追加は /petit admin add でできます！", "tool_calls": []}

    monkeypatch.setattr(brain.lmstudio_client, "chat_completion", fake_chat_completion)

    tc = TestClient(main.app)
    ctx_text = "[Discordチャンネルの参考文脈（直近の発言・返信先）]\n- So: 管理者の追加どうやってやるんだっけ？"
    r = tc.post(
        "/api/channels/discord/events",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={
            "event_id": "9001",
            "channel_id": "8888",
            "guild_id": GUILD,
            "author_id": OWNER,
            "display_name": "So",
            "message": "ぷて",
            "channel_context": ctx_text,
        },
    )
    assert r.status_code == 200
    assert r.json()["reply"] == "管理者の追加は /petit admin add でできます！"
    assert len(captured_messages) == 1
    sent_contents = [m["content"] for m in captured_messages[0]]
    assert ctx_text in sent_contents
    assert sent_contents[-1] == "ぷて"
    assert sent_contents.index(ctx_text) == len(sent_contents) - 2

    # Stored conversation history keeps only the pure user message, not channel_context
    hist = conversation_store.history("discord:8888")
    assert hist == [
        {"role": "user", "content": "ぷて"},
        {"role": "assistant", "content": "管理者の追加は /petit admin add でできます！"},
    ]


def test_core_client_surfaces_http_status_and_timeout_errors():
    async def run(transport):
        core = bot.CoreClient("http://core", TOKEN, transport=transport)
        try:
            return await core.digest_command({"action": "preview", "author_id": OWNER})
        finally:
            await core.close()

    res_401 = asyncio.run(run(httpx.MockTransport(lambda req: httpx.Response(401, json={"detail": "認証できませんでした。"}))))
    assert res_401["reply"] == "認証できませんでした。"

    res_500 = asyncio.run(run(httpx.MockTransport(lambda req: httpx.Response(500, text="Internal Error"))))
    assert "HTTP 500" in res_500["reply"]

    res_503 = asyncio.run(run(httpx.MockTransport(lambda req: httpx.Response(503, json={}))))
    assert "Discord 連携設定" in res_503["reply"]

    timeout = httpx.MockTransport(lambda req: (_ for _ in ()).throw(httpx.ReadTimeout("slow")))
    res_timeout = asyncio.run(run(timeout))
    assert "タイムアウト" in res_timeout["reply"]

    down = httpx.MockTransport(lambda req: (_ for _ in ()).throw(httpx.ConnectError("down")))
    res_down = asyncio.run(run(down))
    assert res_down["reply"] == bot.UNAVAILABLE
