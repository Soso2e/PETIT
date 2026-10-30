"""Persistent-provider isolation and compact-catalog contracts, no external inference."""
import json
import queue
from pathlib import Path
from uuid import uuid4
import pytest
from tests.test_setup_integrations import isolated
from backend import (agent_workspace as workspace, brain, brain_catalog, codex_brain,
    config, conversation_api as api, conversation_store as store, db, request_context, setup_store as settings, tools)


class RPC:
    calls = []
    count = 0
    emit = []
    def __init__(self, *, workspace=None, web_search="disabled"):
        self.workspace = workspace
        self.web_search = web_search
        self.pending = []
        self.events = queue.Queue()
    def request(self, method, params=None, **kwargs):
        self.calls.append((method, params))
        if method == "account/read": return {"account":{"type":"chatgpt"}}
        if method in {"thread/start", "thread/resume"}:
            RPC.count += 1
            self.thread = params.get("threadId", "external-" + str(RPC.count))
            return {"thread":{"id":self.thread},"instructionSources":[str(self.workspace / "AGENTS.md")]}
        if method == "turn/start":
            self.pending = list(RPC.emit) + [
                {"method":"item/agentMessage/delta", "params":{"delta":"途中の文"}},
                {"method":"item/completed", "params":{"item":{"type":"agentMessage", "text":"自然な返答"}}},
                {"method":"turn/completed", "params":{"turn":{"status":"completed"}}}]
        return {}
    def send(self, message): pass
    def close(self): pass


@pytest.fixture
def fake(monkeypatch):
    RPC.calls, RPC.count, RPC.emit = [], 0, []
    monkeypatch.setattr(codex_brain, "RPC", RPC)
    monkeypatch.setattr(brain.lmstudio_client, "endpoint", lambda route: {"provider":"codex", "profile":"codex", "model":"synthetic", "base_url":"", "external":True})
    return RPC


def test_workspace_contains_only_managed_instructions():
    root = workspace.prepare()
    assert {p.name for p in root.iterdir()} == {"AGENTS.md", "CONTEXT.md"}
    assert "PETIT" in (root / "AGENTS.md").read_text(encoding="utf-8")
    (root / "AGENTS.md").write_text("user modification",encoding="utf-8")
    with pytest.raises(ValueError, match="レビュー"):
        workspace.prepare()
    assert (root / "AGENTS.md").read_text() == "user modification"


def test_persistent_thread_restores_without_history_duplication(fake):
    one = api.submit("same-thread", "r1", "架空の合言葉はORBIT", is_admin=True)
    two = api.submit("same-thread", "r2", "続けて", is_admin=True)
    assert one["status"] == two["status"] == "completed"
    assert two["reply"].startswith("自然な返答") and two["model_route"]["resumed"]
    starts = [p for m,p in fake.calls if m == "thread/start"]
    resumes = [p for m,p in fake.calls if m == "thread/resume"]
    assert len(starts) == len(resumes) == 1
    assert starts[0]["ephemeral"] is False and "baseInstructions" not in starts[0]
    prompts = [p["input"][0]["text"] for m,p in fake.calls if m == "turn/start"]
    assert "ORBIT" not in prompts[1]
    with db.get_connection() as c:
        assert c.execute("SELECT count(*) FROM provider_sessions").fetchone()[0] == 1
    # New process/module calls retain only DB-owned correspondence.
    api.submit("same-thread", "r3", "もう一度", is_admin=True)
    assert len([m for m,p in fake.calls if m == "thread/resume"]) == 2


def test_thread_and_admin_boundaries_do_not_share_sessions(fake):
    api.submit("a", "a1", "admin private", is_admin=True)
    api.submit("b", "b1", "other", is_admin=True)
    api.submit("a", "a2", "guest", is_admin=False)
    assert not [m for m,p in fake.calls if m == "thread/resume"]
    starts = [p for m,p in fake.calls if m == "thread/start"]
    assert starts[-1]["dynamicTools"] == []


def test_midturn_failure_cannot_be_resumed(fake, monkeypatch):
    api.submit("a", "a1", "hello", is_admin=True)
    original = fake.request
    def failed(self, method, params=None, **kwargs):
        if method == "turn/start": raise brain.lmstudio_client.LMStudioError("synthetic failure")
        return original(self, method, params, **kwargs)
    monkeypatch.setattr(fake, "request", failed)
    assert api.submit("a", "a2", "fail", is_admin=True)["status"] == "failed"
    with db.get_connection() as c:
        assert c.execute("SELECT count(*) FROM provider_sessions").fetchone()[0] == 0
    monkeypatch.setattr(fake, "request", original)
    api.submit("a", "a3", "recover", is_admin=True)
    assert len([m for m,p in fake.calls if m == "thread/start"]) == 2


def test_guest_cannot_discover_and_external_services_disappear(monkeypatch):
    with request_context.bind(request_id=None, session_id=None, is_admin=False):
        assert brain_catalog.Catalog().schemas() == []
        with pytest.raises(ValueError):brain_catalog.Catalog().discover('{"names":["get_tasks"]}')
    with request_context.bind(request_id=None, session_id=None, is_admin=True):
        catalog = brain_catalog.Catalog()
        names = {x["function"]["name"] for x in catalog.full()}
        assert not {"gmail_search", "gmail_get_message", "search_notion"} & names
        assert {"get_weather", "search_news"} <= names
        assert "start_background_research" not in names
        assert len(catalog.schemas()) <= 6
        assert "get_work_status" in json.loads(catalog.discover('{"names":["get_work_status"]}'))["schemas"][0]["function"]["name"]
        settings.update({"connected":["gmail"]}, {"google_tokens":{"synthetic":True}})
        assert "gmail_search" in {x["function"]["name"] for x in catalog.full()}
        settings.update({"connected":[]})
        with pytest.raises(ValueError):catalog.discover('{"names":["gmail_search"]}')


def test_native_discovery_then_weather_uses_one_brain(monkeypatch):
    from tests.test_renaissance_core import call
    seen = []
    responses = iter([
        {"tool_calls":[call("discover_tools", {"names":["get_work_status"]})]},
        {"tool_calls":[call("get_weather", {"location":"東京"}, "weather-1")]},
        {"content":"取得した天気を説明します"}])
    monkeypatch.setattr(brain.lmstudio_client, "endpoint", lambda route:{"provider":"lm_studio","profile":"local","model":"synthetic","base_url":"http://127.0.0.1"})
    def model(messages, **kwargs):
        seen.append({x["function"]["name"] for x in kwargs["tools"]})
        return next(responses)
    monkeypatch.setattr(brain.lmstudio_client, "chat_completion", model)
    monkeypatch.setattr("backend.web_sources.get_weather", lambda *args:{"location":"東京","temperature":20,"source":"synthetic"})
    result = api.submit("weather", "weather-1", "東京の天気", is_admin=True)
    assert result["status"] == "completed"
    assert "get_work_status" not in seen[0] and "get_work_status" in seen[1]
    assert [x["name"] for x in result["used_tools"]] == ["discover_tools", "get_weather"]
    assert result["model_route"]["llm_call_count"] == 3


def test_native_web_is_disabled_for_guest(fake):
    settings.update({"codex_web_search":"live"})
    api.submit("guest", "guest-r", "hello", is_admin=False)
    assert api.submit("admin", "admin-r", "hello", is_admin=True)["model_route"]["web_search"] == "live"


def test_missing_rollout_restores_core_context(fake, monkeypatch):
    api.submit("a", "a1", "確認済みの架空コードORBIT", is_admin=True)
    original = fake.request
    def missing(self, method, params=None, **kwargs):
        if method == "thread/resume": raise codex_brain.ResumeUnavailable("missing")
        return original(self, method, params, **kwargs)
    monkeypatch.setattr(fake, "request", missing)
    result = api.submit("a", "a2", "続けて", is_admin=True)
    assert result["status"] == "completed" and not result["model_route"]["resumed"]
    assert "ORBIT" in [p["input"][0]["text"] for m,p in fake.calls if m == "turn/start"][-1]


def test_repeated_dynamic_call_is_not_executed_twice(fake, monkeypatch):
    entry = {"id":50, "method":"item/tool/call", "params":{"callId":"same", "threadId":"external-1", "tool":"petit_read_tool",
        "arguments":{"name":"save_memory", "arguments_json":'{"content":"合成検証のみ"}'}}}
    fake.emit = [entry, {**entry,"id":51}]
    # Transport request IDs can differ while the model tool-call ID stays identical.
    # Signature excludes only transport ID because params are identical.
    result = api.submit("a", "a1", "記憶して", is_admin=True)
    assert result["status"] == "completed"
    with db.get_connection() as c:
        assert c.execute("SELECT count(*) FROM effect_receipts WHERE request_id='a1'").fetchone()[0] == 1


def test_local_only_never_exposes_web_reads():
    store.create_thread("local", privacy="local_only")
    with request_context.bind(request_id=None,session_id="local",is_admin=True):
        names = {x["function"]["name"] for x in brain_catalog.Catalog().full()}
        assert not {"get_weather", "search_news", "gmail_search"} & names


def test_weather_missing_place_is_rejected_without_request(monkeypatch):
    from tests.test_renaissance_core import call
    monkeypatch.setattr(brain.lmstudio_client,"endpoint",lambda route:{"provider":"lm_studio","profile":"local","model":"synthetic","base_url":"http://127.0.0.1"})
    replies=iter([{"tool_calls":[call("get_weather",{})]}, {"content":"どこの天気を確認しますか？"}])
    monkeypatch.setattr(brain.lmstudio_client,"chat_completion", lambda *a,**k:next(replies))
    from unittest.mock import Mock
    fetch=Mock();monkeypatch.setattr("backend.web_sources.get_weather",fetch)
    result=api.submit("weather", "w1", "天気は？", is_admin=True)
    assert result["status"] == "completed" and result["used_tools"] == []
    fetch.assert_not_called()


def test_duplicate_provider_thread_is_rejected_before_turn(fake, monkeypatch):
    api.submit("a", "a1", "hello", is_admin=True)
    original = fake.request
    def duplicated(self, method, params=None, **kwargs):
        result = original(self, method, params, **kwargs)
        if method == "thread/start":result["thread"]["id"] = "external-1"
        return result
    monkeypatch.setattr(fake,"request",duplicated)
    result = api.submit("b", "b1", "other thread", is_admin=True)
    assert result["status"] == "failed"
    assert len([m for m,p in fake.calls if m == "turn/start"]) == 1
    with db.get_connection() as c:
        assert c.execute("SELECT thread_id FROM provider_sessions WHERE session_id='external-1'").fetchone()[0] == "a"


def test_catalog_reads_live_policy_once_per_snapshot(monkeypatch):
    from unittest.mock import Mock
    privacy = Mock(return_value=False)
    load = Mock(wraps=settings.load)
    monkeypatch.setattr(request_context,"local_only",privacy)
    monkeypatch.setattr(settings,"load",load)
    assert brain.schemas()
    assert privacy.call_count == load.call_count == 1
