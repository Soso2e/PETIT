"""Life Log ingestion, the staged DeepSeek digest, and daily Discord posts (#504)."""
import asyncio
import json
from datetime import date, datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.test_setup_integrations import isolated  # noqa: F401 - autouse isolation
from backend import config, db, discord_digest, guild_api, life_log
from backend.channels.discord import bot

TOKEN = "t" * 40
OWNER, GUILD = "1001", "2002"
HEADERS = {"Authorization": "Bearer " + TOKEN}


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    inbox = tmp_path / "BRAIN" / "inbox"
    (inbox / "chatgpt").mkdir(parents=True)
    (inbox / "claude").mkdir(parents=True)
    monkeypatch.setenv("PETIT_LIFELOG_INBOX_DIRS", str(inbox))
    monkeypatch.setenv("PETIT_LIFELOG_TIMEZONE", "Asia/Tokyo")
    monkeypatch.setenv("PETIT_LIFELOG_GITHUB", "0")
    monkeypatch.setenv("PETIT_LIFELOG_DISCORD", "0")
    monkeypatch.setattr(config, "AI_DAILY_DIR", tmp_path / "daily")
    monkeypatch.setenv("PETIT_DISCORD_SERVICE_TOKEN", TOKEN)
    monkeypatch.setenv("PETIT_DISCORD_OWNER_ID", OWNER)
    monkeypatch.setenv("PETIT_DISCORD_OWNER_GUILD_IDS", GUILD)
    monkeypatch.delenv("PETIT_DISCORD_GUILD_MODE", raising=False)
    monkeypatch.setattr(life_log, "COLLECTORS", {})
    return inbox


def write(inbox, rel, text):
    path = inbox / rel
    path.write_text(text, encoding="utf-8")
    return path


class FakeLLM:
    def __init__(self, fail=()):
        self.calls = []
        self.fail = set(fail)

    def __call__(self, profile, system, user, max_tokens):
        stage = "extract" if "記録整理係" in system else "merge" if "事実リスト" in system else "compose"
        self.calls.append((stage, profile, user))
        if stage in self.fail:
            raise RuntimeError("down")
        if stage == "extract":
            return json.dumps({"facts": [{"kind": "done", "project": "PETIT", "text": "Discord連携を設計", "src": 1},
                                         {"kind": "next", "project": "", "text": "受入テスト", "src": 99}]})
        if stage == "merge":
            return "```json\n" + json.dumps({"headline": "設計の日", "projects": [
                {"name": "PETIT", "done": ["Discord連携を設計"], "progress": [], "next": []}], "next": ["受入テスト"]}) + "\n```"
        return "設計の日でした。\n- PETIT: Discord連携を設計"


@pytest.fixture
def llm(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(life_log, "_llm", fake)
    monkeypatch.setattr(life_log, "deepseek_configured", lambda: True)
    return fake


# ---------------------------------------------------------------- ingestion


def test_inbox_assigns_day_and_origin_and_skips_unchanged(env):
    write(env, "chatgpt/2026-11-19.md", "- Discord の設計を相談")
    write(env, "claude/log.md", "---\ndate: 2026-11-18\nsource: Claude\ntitle: 実装ログ\n---\n- テストを書いた")
    write(env, ".hidden.md", "見ない")
    write(env, "chatgpt/image.png", "x")
    first = life_log.scan_inbox()
    assert first["changed"] == 2 and first["seen"] == 2
    assert life_log.scan_inbox()["changed"] == 0
    rows = {r["origin"]: r for r in life_log.entries_for("2026-11-19") + life_log.entries_for("2026-11-18")}
    assert rows["chatgpt"]["title"] == "2026-11-19"
    assert rows["claude"]["title"] == "実装ログ" and "テストを書いた" in rows["claude"]["excerpt"]


def test_missing_inbox_folder_is_reported_not_raised(env, monkeypatch, tmp_path):
    monkeypatch.setenv("PETIT_LIFELOG_INBOX_DIRS", str(tmp_path / "nope"))
    assert life_log.scan_inbox()["missing"] == 1


def test_resolve_day():
    now = datetime(2026, 11, 20, 1, 0, tzinfo=timezone.utc)  # 10:00 JST
    assert life_log.resolve_day(None, now) == date(2026, 11, 19)
    assert life_log.resolve_day("today", now) == date(2026, 11, 20)
    assert life_log.resolve_day("2026-11-01") == date(2026, 11, 1)
    with pytest.raises(ValueError):
        life_log.resolve_day("きのうのきのう")


# ---------------------------------------------------------------- staged digest


def test_three_stages_then_cache(env, llm):
    write(env, "chatgpt/2026-11-19.md", "- Discord の設計を相談")
    digest = life_log.generate("2026-11-19")
    assert [c[0] for c in llm.calls] == ["extract", "merge", "compose"]
    assert llm.calls[1][1] == "deepseek_pro" and llm.calls[0][1] == "deepseek_flash"
    assert digest["status"] == "ok" and digest["text"].startswith("**11/19（木）の進捗**")
    assert digest["sources"] == {"chatgpt": 1}
    # the unknown src 99 is dropped instead of trusted
    assert "Discord連携を設計" in digest["text"]
    assert (config.AI_DAILY_DIR / "2026-11-19-activity.md").is_file()

    again = life_log.generate("2026-11-19")
    assert again["cached"] is True and len(llm.calls) == 3

    write(env, "claude/2026-11-19.md", "- テスト追加")
    life_log.generate("2026-11-19")
    extracts = [c for c in llm.calls if c[0] == "extract"]
    assert len(extracts) == 2  # only the changed batch went to stage 1 again


def test_every_stage_falls_back(env, monkeypatch):
    fake = FakeLLM(fail={"extract", "merge", "compose"})
    monkeypatch.setattr(life_log, "_llm", fake)
    monkeypatch.setattr(life_log, "deepseek_configured", lambda: True)
    write(env, "chatgpt/2026-11-19.md", "- Discord の設計を相談\n- 夜はカレー")
    digest = life_log.generate("2026-11-19")
    assert digest["status"] == "degraded"
    assert digest["stages"]["extract"] == "fallback" and digest["stages"]["compose"] == "fallback"
    assert "Discord の設計を相談" in digest["text"]
    assert len(digest["text"]) <= life_log.POST_LIMIT


def test_no_deepseek_key_never_calls_llm(env, monkeypatch):
    monkeypatch.setattr(life_log, "deepseek_configured", lambda: False)
    monkeypatch.setattr(life_log, "_llm", lambda *a: pytest.fail("LLM must not be called"))
    write(env, "chatgpt/2026-11-19.md", "- 何か")
    assert life_log.generate("2026-11-19")["stages"]["llm"] is False


def test_empty_day(env, llm):
    digest = life_log.generate("2026-11-10")
    assert digest["status"] == "empty" and "記録が見つかりませんでした" in digest["text"] and llm.calls == []


def test_failing_source_does_not_stop_digest(env, llm, monkeypatch):
    def broken(day):
        raise RuntimeError("github down")
    monkeypatch.setattr(life_log, "COLLECTORS", {"github": broken})
    write(env, "chatgpt/2026-11-19.md", "- 進めた")
    assert life_log.generate("2026-11-19")["status"] == "ok"


def test_tool_is_read_only_and_registered(env, llm):
    from backend.tools import dispatch, registered_names, requires_confirmation
    assert "get_activity_digest" in registered_names() and not requires_confirmation("get_activity_digest")
    write(env, "chatgpt/2026-11-19.md", "- 進めた")
    result = dispatch("get_activity_digest", {"day": "2026-11-19", "include_entries": True})
    result = result.get("result", result) if isinstance(result, dict) else result
    assert "進捗" in json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------- subscriptions & delivery


@pytest.fixture
def api():
    app = FastAPI()
    app.include_router(discord_digest.router)
    return TestClient(app)


def command(api, **body):
    payload = {"action": "here", "author_id": OWNER, "guild_id": GUILD, "channel_id": "777"}
    payload.update(body)
    return api.post("/api/channels/discord/digests/command", json=payload, headers=HEADERS)


@pytest.mark.parametrize("override", [{"author_id": "9999"}, {"guild_id": "4004"}])
def test_only_owner_in_designated_place_can_register(api, override):
    assert command(api, **override).status_code == 403


def test_register_list_off(api):
    response = command(api, time="9:30")
    assert response.status_code == 200 and "09:30" in response.json()["reply"]
    assert "<#777>" in command(api, action="list").json()["reply"]
    assert command(api, time="25:00").status_code == 400
    assert "止めました" in command(api, action="off").json()["reply"]
    assert "停止中" in command(api, action="list").json()["reply"]


def _set_created(at: str):
    with db.get_connection() as conn:
        conn.execute("UPDATE discord_digest_subscriptions SET created_at=?", (at,))


def test_due_once_per_day_with_catchup_window(api, env, llm):
    write(env, "chatgpt/2026-11-19.md", "- 進めた")
    command(api, time="10:00")
    _set_created("2026-11-18T00:00:00+00:00")
    before = datetime(2026, 11, 20, 0, 59, tzinfo=timezone.utc)  # 09:59 JST
    at = datetime(2026, 11, 20, 1, 0, tzinfo=timezone.utc)       # 10:00 JST
    late = datetime(2026, 11, 20, 8, 0, tzinfo=timezone.utc)     # 17:00 JST, past catch-up
    assert discord_digest.due_subscriptions(before) == []
    assert discord_digest.due_subscriptions(late) == []
    assert [d for _, d in discord_digest.due_subscriptions(at)] == ["2026-11-19"]
    assert discord_digest.run_due(at) == 1
    assert discord_digest.run_due(at) == 0  # never twice

    posts = api.get("/api/channels/discord/digests", headers=HEADERS).json()["posts"]
    assert len(posts) == 1 and posts[0]["channel_id"] == "777" and "進捗" in posts[0]["body"]
    assert api.get("/api/channels/discord/digests", headers=HEADERS).json()["posts"] == []
    assert api.post(f"/api/channels/discord/digests/{posts[0]['post_id']}", json={"status": "sent"},
                    headers=HEADERS).status_code == 200
    assert api.post(f"/api/channels/discord/digests/{posts[0]['post_id']}", json={"status": "sent"},
                    headers=HEADERS).status_code == 404


def test_registering_after_todays_slot_waits_until_tomorrow(api):
    command(api, time="10:00")
    _set_created("2026-11-20T06:00:00+00:00")  # 15:00 JST
    assert discord_digest.due_subscriptions(datetime(2026, 11, 20, 6, 1, tzinfo=timezone.utc)) == []
    assert discord_digest.due_subscriptions(datetime(2026, 11, 21, 1, 0, tzinfo=timezone.utc))


def test_claim_requires_token(api):
    assert api.get("/api/channels/discord/digests", headers={"Authorization": "Bearer nope"}).status_code == 401


# ---------------------------------------------------------------- Bot side


class FakeCore:
    def __init__(self, posts):
        self.posts, self.reports, self.commands = posts, [], []

    async def claim_digests(self):
        return {"posts": self.posts}

    async def report_digest(self, post_id, status, error=None):
        self.reports.append((post_id, status, error))

    async def digest_command(self, body):
        self.commands.append(body)
        return {"reply": "ok"}


class Channel:
    def __init__(self, kind="text"):
        self.type, self.sent, self.threads = kind, [], []

    async def send(self, text):
        self.sent.append(text)

    async def create_thread(self, name, content):
        thread = Channel()
        thread.sent.append(content)
        self.threads.append((name, thread))
        return type("Created", (), {"thread": thread})()


def test_bot_posts_to_text_channel_and_forum():
    text_channel, forum = Channel(), Channel("forum")
    channels = {1: text_channel, 2: forum}

    async def get_channel(cid):
        if cid == 3:
            raise RuntimeError("Forbidden")
        return channels[cid]

    core = FakeCore([{"post_id": 10, "channel_id": "1", "title": "2026-11-19 の進捗", "body": "本文"},
                     {"post_id": 11, "channel_id": "2", "title": "2026-11-19 の進捗", "body": "本文2"},
                     {"post_id": 12, "channel_id": "3", "title": "x", "body": "y"}])
    assert asyncio.run(bot.deliver_digests(core, get_channel)) == 2
    assert text_channel.sent == ["本文"]
    assert forum.threads[0][0] == "2026-11-19 の進捗" and forum.threads[0][1].sent == ["本文2"]
    assert core.reports == [(10, "sent", None), (11, "sent", None), (12, "failed", "RuntimeError")]


def test_slash_digest_relays_target_channel_even_in_dm():
    core = FakeCore([])
    data = {"name": "petit", "options": [{"name": "digest", "options": [
        {"name": "action", "value": "here"}, {"name": "time", "value": "10:00"}, {"name": "channel", "value": "888"}]}]}
    reply = asyncio.run(bot.dispatch_slash_interaction(
        core, interaction_id="1", guild_id=None, author_id=OWNER, display_name="", manage_guild=False,
        permissions=None, data=data, channel_id="555"))
    assert reply == "ok" and core.commands[0]["channel_id"] == "888" and core.commands[0]["guild_id"] is None


# ---------------------------------------------------------------- owner-only Guild endpoints


def test_guild_setup_is_closed_while_owner_only(api):
    app = FastAPI()
    app.include_router(guild_api.router)
    response = TestClient(app).post("/api/guild/setup", json={"guild_id": GUILD, "author_id": "9999", "manage_guild": True},
                                    headers=HEADERS)
    assert response.status_code == 403 and "持ち主専用" in response.json()["detail"]


def test_bot_command_tree_builds_with_digest():
    pytest.importorskip("discord")
    client = bot.build_client(bot.CoreClient("http://127.0.0.1:1", "x" * 40))
    digest = client.tree.get_command("petit").get_command("digest")
    channel = [o for o in digest.to_dict(client.tree)["options"] if o["name"] == "channel"][0]
    assert 15 in channel["channel_types"]  # forum channels can be chosen


# ---------------------------------------------------------------- inbox warnings


def test_inbox_warnings_name_skipped_files(env, monkeypatch, tmp_path):
    write(env, "chatgpt/2026-11-19.md", "- 読める")
    write(env, "chatgpt/会議メモ.gdoc", '{"doc_id": "abc"}')
    write(env, "claude/offline.md", "- 実体がない")
    (env / "big.md").write_text("x" * (life_log.MAX_FILE_BYTES + 1), encoding="utf-8")
    real_read = type(env).read_text

    def flaky_read(self, *args, **kwargs):
        if self.name == "offline.md":
            raise OSError("cloud file not available")
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr(type(env), "read_text", flaky_read)
    monkeypatch.setenv("PETIT_LIFELOG_INBOX_DIRS", f"{env};{tmp_path / 'gone'}")
    scan = life_log.scan_inbox()
    assert scan["changed"] == 1
    notes = "\n".join(life_log.inbox_warnings(scan))
    assert "chatgpt/会議メモ.gdoc" in notes and "Markdown" in notes
    assert "claude/offline.md" in notes and "オフラインで使用可能" in notes
    assert "big.md" in notes and "1MB" in notes
    assert "フォルダが見つかりません" in notes


def test_clean_inbox_has_no_warnings(env):
    write(env, "chatgpt/2026-11-19.md", "- 読める")
    assert life_log.inbox_warnings(life_log.scan_inbox()) == []


def test_preview_shows_warnings_but_scheduled_post_does_not(api, env, llm):
    write(env, "chatgpt/2026-11-19.md", "- 進めた")
    write(env, "chatgpt/メモ.gdoc", "{}")
    preview = command(api, action="preview", day="yesterday").json()
    assert "取り込みの注意" in preview["reply"] and "メモ.gdoc" in preview["reply"]

    command(api, time="10:00")
    _set_created("2026-11-18T00:00:00+00:00")
    discord_digest.run_due(datetime(2026, 11, 20, 1, 0, tzinfo=timezone.utc))
    posts = api.get("/api/channels/discord/digests", headers=HEADERS).json()["posts"]
    assert posts and "gdoc" not in posts[0]["body"] and "取り込みの注意" not in posts[0]["body"]
