"""Isolated acceptance contracts. No real credentials, paid calls, or user DB."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from unittest.mock import Mock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import (setup_store as settings, setup_api, config, db, service_sync as sync,
                     google_services as google, brain_priority as priority, brain,
                     conversation_store as store, conversation_api as conversations, tools)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("PETIT_SETTINGS_DIR", str(tmp_path / "settings"))
    monkeypatch.delenv("PETIT_BOOTSTRAP_TOKEN", raising=False)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "app.db")
    monkeypatch.setattr(config, "NOTION_API_KEY", "")
    monkeypatch.setattr(config, "NOTION_TASKS_DB_ID", "")
    monkeypatch.setattr(config, "NOTION_PROJECTS_DB_ID", "")
    monkeypatch.setattr(config, "TIMETREE_EMAIL", "")
    monkeypatch.setattr(config, "TIMETREE_PASSWORD", "")
    monkeypatch.setattr(config, "TIMETREE_CALENDAR_CODE", "")
    monkeypatch.setattr(config, "notion_configured", lambda: False)
    monkeypatch.setattr(config, "USE_SONA_CORE", False)
    monkeypatch.setattr("backend.chat._artifact_executor.submit", Mock())
    monkeypatch.setattr("backend.chroma_client.add", Mock())
    monkeypatch.setattr("backend.chroma_client.sync_structured_data", Mock())
    setup_api._attempts.clear()
    settings._sessions.clear()
    db.init_db()
    store.ensure_schema()
    sync.ensure_schema()
    tools.register_builtin_tools()


@pytest.fixture
def client():
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(setup_api.router)
    setup_api.install(app)
    # a legacy mutation must be covered by authentication too
    @app.post("/api/model-routing")
    def legacy():
        return {"ok": True}
    return TestClient(app, base_url="http://localhost", client=("127.0.0.1", 12345), headers={"X-PETIT-Request": "1"})


def admin(client):
    response = client.post("/api/setup/bootstrap", json={"password": "synthetic-passphrase"})
    assert response.status_code == 200
    return response


def calendar(service="google_calendar"):
    settings.update({"calendar": service, "connected": [service]}, {"timetree_calendar": "synthetic"})


def event(title="合成予定", external="external-1"):
    return {"id": external, "summary": title, "updated": "2026-10-25T01:00:00Z", "etag": '"test"',
            "start": {"dateTime": "2026-10-25T00:00:00Z"}, "end": {"dateTime": "2026-10-25T01:00:00Z"}}


def test_encrypted_settings_restart_no_secrets_in_public(tmp_path):
    settings.set_password("synthetic-password")
    settings.update({"calendar": "local"}, {"deepseek_key": "SYNTHETIC-SECRET", "google_tokens": {"refresh_token": "REFRESH-SECRET"}})
    content = (settings.root() / "config.enc").read_bytes()
    assert b"SYNTHETIC-SECRET" not in content and b"REFRESH-SECRET" not in content
    assert settings.secret("deepseek_key") == "SYNTHETIC-SECRET"
    assert "SYNTHETIC-SECRET" not in json.dumps(settings.public())
    assert "REFRESH-SECRET" not in json.dumps(settings.public())
    settings._sessions.clear()
    assert settings.authenticate("synthetic-password")
    assert settings.authenticate("wrong") is None
    (settings.root() / "config.enc").write_bytes(b"corruption")
    with pytest.raises(Exception):
        settings.load()


def test_bootstrap_login_csrf_and_legacy_protection(client):
    assert client.get("/api/setup/config").status_code == 401
    assert client.post("/api/setup/bootstrap", json={"password": "short"}).status_code == 400
    response = admin(client)
    assert "HttpOnly" in response.headers["set-cookie"]
    assert client.get("/api/setup/config").status_code == 200
    malformed = client.put("/api/setup/credentials", json={"values": {"deepseek_key": ["SYNTHETIC-SECRET"]}})
    assert malformed.status_code == 422 and "SYNTHETIC-SECRET" not in malformed.text
    assert client.post("/api/setup/bootstrap", json={"password": "other-password"}).status_code == 409
    assert client.put("/api/setup/config", json={"completed": True}).status_code == 422
    assert client.put("/api/setup/config", json={"priority": ["codex", "codex", "deepseek"]}).status_code == 400
    assert client.put("/api/setup/config", json={"calendar": "google_calendar"}).status_code == 400
    assert client.put("/api/setup/config", json={"priority": ["deepseek", "codex", "antigravity"]}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.put("/api/setup/config", json={"priority": ["deepseek", "codex", "antigravity"]}).status_code == 200
    assert settings.load()["priority"][0] == "deepseek"
    assert client.post("/api/setup/logout").status_code == 200
    assert client.post("/api/model-routing").status_code == 401
    assert client.post("/api/setup/login", json={"password": "synthetic-passphrase"}).status_code == 200
    assert client.post("/api/model-routing").status_code == 200


def test_remote_bootstrap_requires_host_token(monkeypatch):
    from fastapi import FastAPI
    app = FastAPI(); app.include_router(setup_api.router); setup_api.install(app)
    remote = TestClient(app, base_url="https://petit.example", client=("192.0.2.1", 123), headers={"X-PETIT-Request": "1"})
    assert remote.post("/api/setup/bootstrap", json={"password": "synthetic-password"}).status_code == 403
    monkeypatch.setenv("PETIT_BOOTSTRAP_TOKEN", "synthetic-bootstrap")
    assert remote.post("/api/setup/bootstrap", json={"password": "synthetic-password", "bootstrap_token": "wrong"}).status_code == 403
    result = remote.post("/api/setup/bootstrap", json={"password": "synthetic-password", "bootstrap_token": "synthetic-bootstrap"})
    assert result.status_code == 200 and "Secure" in result.headers["set-cookie"]


def test_google_oauth_pkce_state_session_and_grants(client, monkeypatch):
    admin(client)
    settings.update({"google_redirect_uri": "http://localhost/api/setup/google/callback"},
                    {"google_client_id": "synthetic-id", "google_client_secret": "synthetic-secret"})
    result = client.post("/api/setup/google/google_calendar/authorize").json()
    from urllib.parse import urlsplit, parse_qs
    query = parse_qs(urlsplit(result["url"]).query)
    assert query["scope"] == [google.SCOPES["google_calendar"]]
    assert query["code_challenge_method"] == ["S256"]
    response = httpx.Response(200, json={"access_token": "synthetic-access", "refresh_token": "synthetic-refresh", "scope": google.SCOPES["google_calendar"], "expires_in": 3600})
    mocked = Mock(return_value=response); monkeypatch.setattr(httpx, "post", mocked)
    session = client.cookies.get("petit_admin")
    with pytest.raises(ValueError):
        google.callback("wrong", "code", session)
    with pytest.raises(ValueError):
        google.callback(query["state"][0], "code", "other-session")
    assert google.callback(query["state"][0], "synthetic-code", session) == "google_calendar"
    assert "code_verifier" in mocked.call_args.kwargs["data"]
    with pytest.raises(ValueError):
        google.callback(query["state"][0], "synthetic-code", session)
    second = google.authorize("gmail", session)
    scopes = parse_qs(urlsplit(second["url"]).query)["scope"][0]
    assert google.SCOPES["gmail"] in scopes and google.SCOPES["google_calendar"] in scopes
    assert "calendar.events" not in scopes


def test_google_refresh_and_disconnect_only_one_service(monkeypatch):
    settings.update({"connected": ["gmail", "google_calendar"]}, {"google_client_id": "id", "google_tokens": {
        "scopes": list(google.SCOPES.values()), "expires": 0, "refresh_token": "old-refresh", "access_token": "old"}})
    mock = Mock(return_value=httpx.Response(200, json={"access_token": "renewed", "expires_in": 3600}))
    monkeypatch.setattr(httpx, "post", mock)
    assert google.access_token("gmail") == "renewed"
    assert google.access_token("gmail") == "renewed" and mock.call_count == 1
    assert settings.secret("google_tokens")["refresh_token"] == "old-refresh"
    google.disconnect("gmail")
    assert settings.secret("google_tokens")["refresh_token"] == "old-refresh"
    with pytest.raises(google.ServiceError):
        google.access_token("gmail")
    assert google.access_token("google_calendar") == "renewed"


def test_calendar_delta_noop_delete_and_local_survival(monkeypatch):
    calendar()
    mocked = Mock(return_value=([event()], "cursor-1", True));monkeypatch.setattr(google, "calendar_changes", mocked)
    assert sync.sync(manual=True)["updated_count"] == 1
    with db.get_connection() as c:
        row = dict(c.execute("SELECT * FROM calendar_events_cache").fetchone())
        c.execute("INSERT INTO calendar_events_cache(source,title,start_time,updated_at) VALUES('local','local','2026-10-25','now')")
    mocked.return_value = ([event()], "cursor-2", False)
    assert sync.sync(manual=True)["updated_count"] == 0
    with db.get_connection() as c:
        same = dict(c.execute("SELECT * FROM calendar_events_cache WHERE id=?", (row["id"],)).fetchone())
    assert row == same and row["start_time"].startswith("2026-10-25T09:00")
    mocked.return_value = ([{"id": "external-1", "status": "cancelled"}], "cursor-3", False)
    assert sync.sync(manual=True)["updated_count"] == 1
    with db.get_connection() as c:
        assert c.execute("SELECT count(*) FROM calendar_events_cache").fetchone()[0] == 1
        assert c.execute("SELECT title FROM calendar_events_cache").fetchone()[0] == "local"
        assert c.execute("SELECT cursor FROM service_sync_state").fetchone()[0] == "cursor-3"


def test_sync_failure_keeps_snapshot_cursor_and_alert_after_notification_failure(monkeypatch):
    calendar();mock = Mock(return_value=([event()], "good-cursor", True));monkeypatch.setattr(google, "calendar_changes", mock)
    assert sync.sync(manual=True)["ok"]
    mock.side_effect = google.ServiceError("rate_limited", 429)
    deliver = Mock(side_effect=RuntimeError("notification unavailable"));monkeypatch.setattr("backend.notifications.dispatch_notification", deliver)
    assert not sync.sync(manual=True)["ok"]
    assert not sync.sync(manual=True)["ok"]
    assert deliver.call_count == 1
    with db.get_connection() as c:
        assert c.execute("SELECT count(*) FROM calendar_events_cache").fetchone()[0] == 1
        assert c.execute("SELECT cursor FROM service_sync_state").fetchone()[0] == "good-cursor"
    assert len(sync.status()["alerts"]) == 1 and "Googleカレンダー" in sync.warning()
    mock.side_effect = None;mock.return_value = ([], "next-cursor", False)
    assert sync.sync(manual=True)["ok"]
    assert sync.status()["alerts"] == [] and sync.warning() == ""
    assert not sync.status()["states"][0]["error"]


def test_scheduler_2am_boundary_restart_and_single_claim(monkeypatch):
    calendar();mock = Mock(return_value=([], "cursor", True));monkeypatch.setattr(google, "calendar_changes", mock)
    before = datetime.fromisoformat("2026-10-25T01:59:59+09:00")
    after = datetime.fromisoformat("2026-10-25T02:00:00+09:00")
    assert sync.sync(now=before)["ok"]
    assert sync.sync(now=before)["skipped"]
    assert sync.sync(now=after)["ok"]
    assert sync.sync(now=after)["skipped"]
    assert mock.call_count == 2
    with db.get_connection() as c:
        assert c.execute("SELECT slot FROM service_sync_state").fetchone()[0] == "2026-10-25"
    assert sync.sync(now=datetime.fromisoformat("2026-10-27T11:00:00+09:00"))["ok"]
    assert sync.sync(now=datetime.fromisoformat("2026-10-27T11:01:00+09:00"))["skipped"]


def test_concurrent_sync_does_not_duplicate_fetch(monkeypatch):
    calendar();entered=threading.Event();release=threading.Event()
    def fetch(*args):
        entered.set();assert release.wait(5);return [event()], "cursor", True
    mock=Mock(side_effect=fetch);monkeypatch.setattr(google, "calendar_changes", mock)
    worker=threading.Thread(target=lambda: sync.sync(manual=True));worker.start()
    try:
        assert entered.wait(5)
        assert sync.sync(manual=True)["busy"]
    finally:
        release.set();worker.join(5)
    assert mock.call_count == 1


def test_google_410_pagination_preserves_token_until_full_success(monkeypatch):
    results = [google.ServiceError("service_error",410), {"items": [event()], "nextPageToken": "next"}, {"items": [], "nextSyncToken": "fresh"}]
    mocked=Mock(side_effect=results);monkeypatch.setattr(google,"get",mocked)
    items,token,full=google.calendar_changes("primary","expired")
    assert full and token=="fresh" and len(items)==1
    assert "syncToken" not in mocked.call_args_list[1].args[2]
    assert mocked.call_args_list[2].args[2]["pageToken"]=="next"


def test_gmail_tools_read_only_and_body(monkeypatch):
    body=base64.urlsafe_b64encode("合成メール本文".encode()).decode()
    get=Mock(side_effect=[{"messages":[{"id":"mail-1"}]},{"payload":{"headers":[{"name":"Subject","value":"合成件名"}]}},
                         {"id":"mail-1","payload":{"mimeType":"text/plain","body":{"data":body}}}])
    monkeypatch.setattr(google,"get",get)
    search=json.loads(tools.dispatch("gmail_search", {"query":"subject:合成"}))
    assert search["messages"][0]["subject"]=="合成件名"
    detail=json.loads(tools.dispatch("gmail_get_message", {"message_id":"mail-1"}))
    assert detail["body"]=="合成メール本文" and detail["read_only"]
    assert tools.risk_for("gmail_search")==tools.risk_for("gmail_get_message")=="safe_read"
    assert {"gmail_search","gmail_get_message","search_notion"} <= brain.PUBLIC_TOOLS


def configure_priority(monkeypatch):
    settings.update({"brain_enabled":True,"connected":["codex","antigravity","deepseek"],"paid_allowed":["deepseek"]}, {"deepseek_key":"synthetic"})
    def target(provider):
        return {"provider": provider, "profile": provider,"model":"synthetic","base_url":"", "configured":True,"external":True,"api_key":""}
    monkeypatch.setattr(priority,"target",target)
    store.create_thread("thread");store.accept("thread","request",{"message":"hello"});store.claim("request")


def test_priority_fallback_and_top_recovery_use_one_attempt_at_a_time(monkeypatch):
    configure_priority(monkeypatch);seen=[]
    def run(request_id, **kwargs):
        name=priority.current()["profile"];seen.append(name)
        if name=="codex":raise brain.lmstudio_client.LMStudioError("connection failed")
        return {"ok":True}
    assert priority.run("request",run)["ok"]
    assert seen==["codex","antigravity"] and priority.current() is None
    seen.clear()
    assert priority.run("request",lambda *a,**k: seen.append(priority.current()["profile"]) or {"ok":True})["ok"]
    assert seen==["codex"]


def test_paid_fallback_requires_prior_consent(monkeypatch):
    configure_priority(monkeypatch);settings.update({"connected":["deepseek"],"paid_allowed":[]})
    run=Mock()
    with pytest.raises(brain.lmstudio_client.LMStudioError):priority.run("request",run)
    run.assert_not_called()
    settings.update({"paid_allowed":["deepseek"]})
    assert priority.run("request",lambda *a,**k: priority.current()["profile"])=="deepseek"


@pytest.mark.parametrize("kind", ["receipt","read","approval"])
def test_no_runtime_restart_after_any_tool_or_approval(monkeypatch,kind):
    configure_priority(monkeypatch);seen=[]
    def run(request_id, **kwargs):
        seen.append(priority.current()["profile"])
        with db.get_connection() as c:
            if kind=="read":store.event(c,"thread",request_id,"external_tool_started",{"tool":"get_tasks"})
            elif kind=="receipt":c.execute("INSERT INTO effect_receipts VALUES(?,?,?,?,?,?,?)",(request_id,"call","save_memory","{}","unknown",None,db.now_iso()))
            else:c.execute("INSERT INTO turn_approvals VALUES(?,?,?,?,?,?,?)",("approval",request_id,"call","add_schedule","{}","pending",9999999999))
        raise brain.lmstudio_client.LMStudioError("failed after Tool")
    with pytest.raises(brain.lmstudio_client.LMStudioError):priority.run("request",run)
    assert seen==["codex"]


def test_conversation_warns_persistently_and_resolves(monkeypatch):
    sync.fail("google_calendar","synthetic failure")
    monkeypatch.setattr(brain.lmstudio_client,"chat_completion",lambda *a,**k:{"role":"assistant","content":"通常の返答"})
    for i in range(2):
        result=conversations.submit("alert-thread",f"alert-{i}","こんにちは")
        assert result["status"]=="completed"
        assert "通常の返答" in result["reply"] and result["reply"].count("同期が失敗")==1
    sync.resolve("google_calendar")
    assert "同期が失敗" not in conversations.submit("alert-thread","alert-2","こんにちは")["reply"]


def test_setup_calendar_filters_inactive_sources(monkeypatch):
    settings.set_password("synthetic-password");calendar()
    with db.get_connection() as c:
        for source,key,title in [("local",None,"local"),("google_calendar",sync.source_key(),"active"),("timetree","old-timetree","inactive")]:
            c.execute("INSERT INTO calendar_events_cache(source,source_key,title,start_time,updated_at) VALUES(?,?,?,?,?)",(source,key,title,"2026-10-25","now"))
    from backend.tools.schedule import get_schedule
    assert {x["title"] for x in get_schedule()["events"]}=={"local","active"}
    from backend.briefing import _events_for
    assert {x["title"] for x in _events_for("2026-10-25")}=={"local","active"}
    settings.update({"calendar":"local"})
    assert {x["title"] for x in get_schedule()["events"]}=={"local"}
    assert {x["title"] for x in _events_for("2026-10-25")}=={"local"}


def test_sdk_core_bridge_write_receipt_and_approval_resume(monkeypatch):
    from backend import antigravity_brain as sdk
    settings.update({"brain_enabled": True, "priority": ["antigravity", "codex", "deepseek"],
                     "connected": ["antigravity"], "antigravity_model": "synthetic"})
    monkeypatch.setattr(sdk, "installed", lambda: True)
    count = []
    def runtime(request_id, target, instructions, prompt, used, metadata):
        count.append(request_id)
        if not store.approvals(request_id):
            with db.get_connection() as c:
                done = c.execute("SELECT 1 FROM effect_receipts WHERE request_id=?", (request_id,)).fetchone()
            if done:
                return "保存結果を確認しました。"
        read = sdk.bridge(request_id, target, used)
        read("add_schedule", '{"title":"合成承認予定","start_time":"2026-10-25T12:00:00+09:00"}')
        return ""
    monkeypatch.setattr(sdk, "run_isolated", runtime)
    result = conversations.submit("sdk-write", "sdk-write-1", "合成予定を追加")
    assert result["status"] == "waiting_approval"
    with db.get_connection() as c:
        assert c.execute("SELECT count(*) FROM calendar_events_cache").fetchone()[0] == 0
    approved = conversations.decide(store.approvals("sdk-write-1")[0]["approval_id"], True)
    assert approved["status"] == "completed"
    replay = conversations.submit("sdk-write", "sdk-write-1", "合成予定を追加")
    assert replay["reply"] == approved["reply"] and len(count) == 2
    with db.get_connection() as c:
        assert c.execute("SELECT count(*) FROM calendar_events_cache WHERE title='合成承認予定'").fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM effect_receipts").fetchone()[0] == 1


def test_sync_failure_notification_is_high_priority_and_auto_resolved():
    from backend import notifications
    sync.fail("google_calendar", "synthetic failure")
    assert notifications.get_preferences()["sync_failure"]
    with db.get_connection() as c:
        event = c.execute("SELECT * FROM notification_events WHERE category='sync_failure'").fetchone()
        assert json.loads(event["payload_json"])["priority"] == "high"
    sync.resolve("google_calendar")
    with db.get_connection() as c:
        assert c.execute("SELECT resolved_at FROM notification_events WHERE id=?", (event["id"],)).fetchone()[0]
