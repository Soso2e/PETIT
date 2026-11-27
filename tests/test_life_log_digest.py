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
    monkeypatch.setenv("PETIT_LIFELOG_INBOX", "1")
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
    assert digest["payload"]["projects"] and not digest["payload"]["projects"][0]["done"]  # never "done"
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
    assert "chatgpt/会議メモ.gdoc" in notes and "Google Drive" in notes
    assert "claude/offline.md" in notes and "オフラインで使用可能" in notes
    assert "big.md" in notes and "1MB" in notes
    assert "フォルダが見つかりません" in notes


def test_clean_inbox_has_no_warnings(env):
    write(env, "chatgpt/2026-11-19.md", "- 読める")
    assert life_log.inbox_warnings(life_log.scan_inbox()) == []


def test_preview_and_scheduled_post_omit_inbox_warnings_section(api, env, llm):
    write(env, "chatgpt/2026-11-19.md", "- 進めた")
    write(env, "chatgpt/メモ.gdoc", "{}")
    preview = command(api, action="preview", day="yesterday").json()
    assert "取り込みの注意" not in preview["reply"] and "メモ.gdoc" not in preview["reply"]

    command(api, time="10:00")
    _set_created("2026-11-18T00:00:00+00:00")
    discord_digest.run_due(datetime(2026, 11, 20, 1, 0, tzinfo=timezone.utc))
    posts = api.get("/api/channels/discord/digests", headers=HEADERS).json()["posts"]
    assert posts and "gdoc" not in posts[0]["body"] and "取り込みの注意" not in posts[0]["body"]


def test_inbox_is_disabled_by_default_and_ignored_in_digest(env, llm, monkeypatch):
    write(env, "chatgpt/2026-11-22.md", "- BRAIN側の古いログ")
    write(env, "chatgpt/メモ.gdoc", '{"doc_id": "abc"}')
    life_log.scan_inbox()
    assert life_log.entries_for("2026-11-22")

    monkeypatch.delenv("PETIT_LIFELOG_INBOX", raising=False)
    assert life_log.inbox_enabled() is False
    monkeypatch.setattr(life_log, "COLLECTORS", {
        "notion": lambda day: [{
            "source": "notion",
            "origin": "notion",
            "ref": f"page-1@{day.isoformat()}",
            "day": day.isoformat(),
            "title": "日報",
            "body": "- Notion の日報だけを使う",
        }]
    })
    digest = life_log.generate("2026-11-22", audience="shared")
    assert digest["status"] == "ok"
    assert digest["sources"] == {"notion": 1}
    assert digest["warnings"] == []
    assert digest["diagnostics"]["raw_sources"] == {"notion": 1}



# ---------------------------------------------------------------- Google Docs (.gdoc) via Drive, day shift


class FakeDrive:
    def __init__(self, texts):
        self.texts, self.calls = texts, []

    def __call__(self, file_id):
        self.calls.append(file_id)
        if file_id not in self.texts:
            from backend.google_services import ServiceError
            raise ServiceError("authentication_expired", 401)
        return {"id": file_id, "name": "x", "modified": "", "text": self.texts[file_id], "read_only": True}


@pytest.fixture
def drive(monkeypatch):
    from backend import google_services
    fake = FakeDrive({"doc-1": "\ufeff\\---\r\ndate: 2026-11-20\r\nsource: chatgpt\r\n\\---\r\n\\# 今日の概要\r\n\\#\\# 【新規】SyncMon の端末別同期"})
    monkeypatch.setattr(google_services, "drive_export_text", fake)
    monkeypatch.setattr(life_log, "drive_connected", lambda: True)
    return fake


def test_gdoc_is_read_through_drive_and_cached(env, drive, monkeypatch):
    monkeypatch.setenv("PETIT_LIFELOG_DAY_SHIFT", "00_Inbox=-1")
    inbox = env / "00_Inbox"
    inbox.mkdir()
    write(env, "00_Inbox/2026-11-20_0900_デイリー知識ログ.md.gdoc", json.dumps({"": "WARNING", "doc_id": "doc-1"}))
    scan = life_log.scan_inbox()
    assert scan["changed"] == 1 and life_log.inbox_warnings(scan) == []
    rows = life_log.entries_for("2026-11-19")  # dated 11/20 09:00, describes 11/19
    assert len(rows) == 1 and rows[0]["origin"] == "chatgpt" and rows[0]["title"] == "2026-11-20_0900_デイリー知識ログ"
    assert rows[0]["excerpt"].startswith("# 今日の概要") and "## 【新規】SyncMon" in rows[0]["excerpt"]
    life_log.scan_inbox()
    assert drive.calls == ["doc-1"]  # unchanged stub -> cached, no second export


def test_gdoc_auth_error_is_reported(env, drive):
    write(env, "chatgpt/2026-11-19.md.gdoc", json.dumps({"doc_id": "missing"}))
    notes = "\n".join(life_log.inbox_warnings(life_log.scan_inbox()))
    assert "認証が切れています" in notes and "chatgpt/2026-11-19.md.gdoc" in notes


def test_gdoc_without_drive_connection_is_a_warning(env, monkeypatch):
    monkeypatch.setattr(life_log, "drive_connected", lambda: False)
    write(env, "chatgpt/2026-11-19.md.gdoc", json.dumps({"doc_id": "doc-1"}))
    notes = "\n".join(life_log.inbox_warnings(life_log.scan_inbox()))
    assert "Step 4" in notes


def test_covers_wins_over_shift_and_top_level_origin_is_folder_name(env, monkeypatch, tmp_path):
    outputs = tmp_path / "70_Outputs"
    outputs.mkdir()
    monkeypatch.setenv("PETIT_LIFELOG_INBOX_DIRS", str(outputs))
    monkeypatch.setenv("PETIT_LIFELOG_DAY_SHIFT", "70_Outputs=-1")
    (outputs / "2026-11-20_Media_a.md").write_text("- 投稿案", encoding="utf-8")
    (outputs / "b.md").write_text("---\ndate: 2026-11-20\ncovers: 2026-11-18\n---\n- 振り返り", encoding="utf-8")
    life_log.scan_inbox()
    assert [r["origin"] for r in life_log.entries_for("2026-11-19")] == ["70_outputs"]
    assert [r["title"] for r in life_log.entries_for("2026-11-18")] == ["b"]


def test_drive_export_text_reads_metadata_then_exports_plain_text(monkeypatch):
    import httpx
    from backend import google_services
    seen = []

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.append((url, params))
        if url.endswith("/export"):
            return httpx.Response(200, content="﻿こんにちは".encode())
        return httpx.Response(200, json={"id": "abc", "name": "n", "mimeType": "application/vnd.google-apps.document"})

    monkeypatch.setattr(google_services, "access_token", lambda service: "tok")
    monkeypatch.setattr(google_services.httpx, "get", fake_get)
    assert google_services.drive_export_text("abc")["text"] == "こんにちは"
    assert seen[1][0].startswith("https://www.googleapis.com/drive/v3/files/abc/export")
    assert seen[1][1] == {"mimeType": "text/plain"}
    with pytest.raises(ValueError):
        google_services.drive_export_text("../x")


def test_deepseek_key_from_setup_screen_is_used(monkeypatch):
    from backend import setup_store
    monkeypatch.delenv("PETIT_DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(setup_store, "load", lambda: {"secrets": {"deepseek_key": "sk-from-setup"}})
    target = life_log._deepseek_target("deepseek_flash")
    assert target["configured"] and target["api_key"] == "sk-from-setup"
    assert life_log.deepseek_configured()


# ---------------------------------------------------------------- privacy, destinations, failures


def test_prompts_exclude_private_content_briefly():
    for prompt in (life_log._EXTRACT_SYSTEM, life_log._COMPOSE_SYSTEM):
        assert "private" in prompt
    assert "人間関係" in life_log._EXTRACT_SYSTEM


def test_shared_audience_keeps_work_only(env, monkeypatch):
    class Mixed(FakeLLM):
        def __call__(self, profile, system, user, max_tokens):
            if "記録整理係" in system:
                self.calls.append(("extract", profile, user))
                return json.dumps({"facts": [
                    {"kind": "done", "project": "PETIT", "text": "設計した", "src": 1},
                    {"kind": "life", "project": "", "text": "友人との相談", "src": 1},
                    {"kind": "blocker", "project": "", "text": "人間関係で悩む", "src": 1}]})
            return super().__call__(profile, system, user, max_tokens)
    fake = Mixed()
    monkeypatch.setattr(life_log, "_llm", fake)
    monkeypatch.setattr(life_log, "deepseek_configured", lambda: True)
    write(env, "chatgpt/2026-11-19.md", "- 設計\n- 友人との相談")
    shared = life_log.generate("2026-11-19", audience="shared")
    merge_input = next(c[2] for c in fake.calls if c[0] == "merge")
    assert "友人" not in merge_input and "悩む" not in merge_input and "設計した" in merge_input
    assert shared["status"] == "ok"
    private = life_log.generate("2026-11-19", audience="private")  # audience is part of the cache key
    assert private["cached"] is False
    assert "友人との相談" in next(c[2] for c in fake.calls[3:] if c[0] == "merge")


def test_shared_audience_drops_chat_sources(env, llm, monkeypatch):
    monkeypatch.setattr(life_log, "COLLECTORS", {"discord": lambda day: [
        {"source": "discord", "origin": "dm", "ref": "m1", "day": day.isoformat(), "title": "t", "body": "秘密の相談"}]})
    digest = life_log.generate("2026-11-19", audience="shared")
    assert digest["status"] == "empty" and llm.calls == []


def test_destination_decides_audience(api, env, llm, monkeypatch):
    seen = []
    real = life_log.generate
    monkeypatch.setattr(life_log, "generate", lambda day, **kw: seen.append(kw["audience"]) or real(day, **kw))
    write(env, "chatgpt/2026-11-19.md", "- 進めた")
    command(api, time="10:00")                       # server channel
    command(api, channel_id="888", guild_id=None)    # DM
    _set_created("2026-11-18T00:00:00+00:00")
    discord_digest.run_due(datetime(2026, 11, 20, 1, 0, tzinfo=timezone.utc))
    assert sorted(seen) == ["private", "shared"]


@pytest.mark.parametrize("case", ["exception", "fallback", "empty"])
def test_failed_summary_is_recorded_not_posted(api, env, monkeypatch, case):
    if case == "exception":
        monkeypatch.setattr(life_log, "generate", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    elif case == "fallback":
        monkeypatch.setattr(life_log, "_llm", FakeLLM(fail={"extract", "merge", "compose"}))
        monkeypatch.setattr(life_log, "deepseek_configured", lambda: True)
        write(env, "chatgpt/2026-11-19.md", "- 未完了の作業")
    command(api, time="10:00")
    _set_created("2026-11-18T00:00:00+00:00")
    assert discord_digest.run_due(datetime(2026, 11, 20, 1, 0, tzinfo=timezone.utc)) == 0
    assert api.get("/api/channels/discord/digests", headers=HEADERS).json()["posts"] == []
    with db.get_connection() as conn:
        row = conn.execute("SELECT status, body, error FROM discord_digest_posts").fetchone()
    assert row["status"] == "failed" and row["body"] == "" and row["error"]
    assert "直近の失敗: 2026-11-19" in command(api, action="list").json()["reply"]
    assert discord_digest.run_due(datetime(2026, 11, 20, 1, 0, tzinfo=timezone.utc)) == 0  # one row per day


def test_preview_says_degraded_digest_is_not_posted(api, env, monkeypatch):
    monkeypatch.setattr(life_log, "deepseek_configured", lambda: False)
    write(env, "chatgpt/2026-11-19.md", "- 作業")
    reply = command(api, action="preview").json()["reply"]
    assert "定時投稿されません" in reply


def test_register_and_unregister_commands(api):
    assert "登録しました" in command(api, action="register").json()["reply"]
    assert "止めました" in command(api, action="unregister").json()["reply"]
    assert "停止中" in command(api, action="list").json()["reply"]
    assert "登録がありません" in command(api, action="unregister", channel_id="999").json()["reply"]


def test_unregister_cancels_unsent_posts(api, env, llm):
    write(env, "chatgpt/2026-11-19.md", "- 進めた")
    command(api, time="10:00")
    _set_created("2026-11-18T00:00:00+00:00")
    assert discord_digest.run_due(datetime(2026, 11, 20, 1, 0, tzinfo=timezone.utc)) == 1
    command(api, action="unregister")
    command(api, action="register")
    assert api.get("/api/channels/discord/digests", headers=HEADERS).json()["posts"] == []


def test_slash_digest_defaults_to_register():
    core = FakeCore([])
    data = {"name": "petit", "options": [{"name": "digest", "options": []}]}
    asyncio.run(bot.dispatch_slash_interaction(
        core, interaction_id="1", guild_id=GUILD, author_id=OWNER, display_name="", manage_guild=False,
        permissions=None, data=data, channel_id="555"))
    assert core.commands[0]["action"] == "register"


def test_notion_collects_daily_report_and_filters_hidden_or_non_report(monkeypatch):
    from backend import notion_client, notion_search

    monkeypatch.setattr(config, "NOTION_API_KEY", "secret-test-key")
    monkeypatch.delenv("PETIT_LIFELOG_NOTION", raising=False)
    monkeypatch.delenv("PETIT_LIFELOG_NOTION_DB_ID", raising=False)

    calls = []

    def fake_post(path, body, timeout=15):
        calls.append((path, body))
        if path == "/search":
            return {
                "results": [
                    {
                        "object": "database",
                        "id": "db-act-schedule",
                        "title": [{"plain_text": "Act Schedule"}],
                    }
                ]
            }
        if path == "/databases/db-act-schedule/query":
            assert body["filter"] == {"property": "Date", "date": {"equals": "2026-11-22"}}
            return {
                "results": [
                    {
                        "id": "page-report",
                        "properties": {
                            "名前": {"type": "title", "title": [{"plain_text": "競馬予測とAI開発"}]},
                            "Date": {"type": "date", "date": {"start": "2026-11-22"}},
                            "States": {"type": "status", "status": {"name": "📓"}},
                            "hide": {"type": "checkbox", "checkbox": False},
                            "ditail": {"type": "rich_text", "rich_text": [{"plain_text": "PETIT開発を進めた"}]},
                            "Cat": {"type": "multi_select", "multi_select": [{"name": "活動"}]},
                        },
                    },
                    {
                        "id": "page-task",
                        "properties": {
                            "名前": {"type": "title", "title": [{"plain_text": "未完了タスク"}]},
                            "Date": {"type": "date", "date": {"start": "2026-11-22"}},
                            "States": {"type": "status", "status": {"name": "yet"}},
                            "hide": {"type": "checkbox", "checkbox": False},
                        },
                    },
                    {
                        "id": "page-hidden",
                        "properties": {
                            "名前": {"type": "title", "title": [{"plain_text": "非公開メモ"}]},
                            "Date": {"type": "date", "date": {"start": "2026-11-22"}},
                            "States": {"type": "status", "status": {"name": "📓"}},
                            "hide": {"type": "checkbox", "checkbox": True},
                        },
                    },
                ]
            }
        raise AssertionError(f"unexpected POST {path}")

    monkeypatch.setattr(notion_client, "_post", fake_post)
    monkeypatch.setattr(notion_search, "_page_text", lambda pid, max_chars: "日報\n- Discord連携を修正" if pid == "page-report" else "")

    items = life_log._collect_notion(date(2026, 11, 22))
    assert len(items) == 1
    assert items[0]["source"] == "notion"
    assert items[0]["day"] == "2026-11-22"
    assert items[0]["title"] == "競馬予測とAI開発"
    assert "PETIT開発を進めた" in items[0]["body"]
    assert "Discord連携を修正" in items[0]["body"]
    assert [c[0] for c in calls] == ["/search", "/databases/db-act-schedule/query"]


def test_notion_shared_audience_includes_daily_report(env, llm, monkeypatch):
    monkeypatch.setattr(life_log, "COLLECTORS", {
        "notion": lambda day: [{
            "source": "notion",
            "origin": "notion",
            "ref": f"page-1@{day.isoformat()}",
            "day": day.isoformat(),
            "title": "日報",
            "body": "- PETIT の機能改善",
        }]
    })
    digest = life_log.generate("2026-11-22", audience="shared")
    assert digest["status"] == "ok"
    assert digest["sources"] == {"notion": 1}


def test_notion_collector_skips_when_disabled_or_unconfigured(monkeypatch):
    monkeypatch.setattr(config, "NOTION_API_KEY", "")
    assert life_log._collect_notion(date(2026, 11, 22)) == []

    monkeypatch.setattr(config, "NOTION_API_KEY", "secret-test-key")
    monkeypatch.setenv("PETIT_LIFELOG_NOTION", "0")
    assert life_log._collect_notion(date(2026, 11, 22)) == []


def test_preview_diagnostics_explain_shared_filter_and_source_errors(api, env, monkeypatch):
    def broken_notion(day):
        raise RuntimeError("notion_boom")

    monkeypatch.setattr(life_log, "COLLECTORS", {
        "discord": lambda day: [{
            "source": "discord",
            "origin": "dm",
            "ref": "m1",
            "day": day.isoformat(),
            "title": "chat",
            "body": "雑談した",
        }],
        "notion": broken_notion,
    })
    res = command(api, action="review", day="yesterday")
    assert res.status_code == 200
    reply = res.json()["reply"]
    assert "定時投稿されません" in reply
    assert "discord=1件" in reply
    assert "除外されました" in reply
    assert "notion: RuntimeError: notion_boom" in reply


def test_preview_diagnostics_explain_llm_error_and_exception(api, env, monkeypatch):
    monkeypatch.setattr(life_log, "deepseek_configured", lambda: True)
    monkeypatch.setattr(life_log, "_llm", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("llm_slow")))
    monkeypatch.setattr(life_log, "COLLECTORS", {
        "github": lambda day: [{
            "source": "github",
            "origin": "github",
            "ref": "r1",
            "day": day.isoformat(),
            "title": "PETIT",
            "body": "- 修正した",
        }],
    })
    res = command(api, action="preview", day="yesterday")
    assert res.status_code == 200
    reply = res.json()["reply"]
    assert "要約ステップのエラー" in reply
    assert "TimeoutError" in reply

    monkeypatch.setattr(life_log, "generate", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("unexpected")))
    res_err = command(api, action="preview", day="yesterday")
    assert res_err.status_code == 200
    assert "RuntimeError" in res_err.json()["reply"]
