"""Codex protocol/Core contracts with synthetic RPC, never real credentials."""
import json
import queue
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend import codex_brain as codex, brain, brain_priority as priority, db
from backend import setup_store as settings, conversation_store as store, conversation_api as conversations
from tests.test_setup_integrations import isolated, client, admin, configure_priority


def delta(text="合成CLI応答"):
    return {"method": "item/agentMessage/delta", "params": {"delta": text}}


def complete(status="completed"):
    return {"method": "turn/completed", "params": {"turn": {"status": status}}}


def tool(name="get_current_time", arguments=None, ident=700, **extra):
    return {"id": ident, "method": "item/tool/call", "params": {
        "threadId": "synthetic-cli-thread", "callId": "call-" + str(ident), "tool": "petit_read_tool",
        "arguments": {"name": name, "arguments_json": json.dumps(arguments or {})}, **extra}}


class FakeRPC:
    scripts = []
    clients = []

    def __init__(self):
        self.temp = SimpleNamespace(name="synthetic-empty-directory")
        self.pending = list(type(self).scripts.pop(0))
        self.events = queue.Queue()
        self.requests, self.sent, self.closed = [], [], False
        type(self).clients.append(self)

    def request(self, method, params=None, **kwargs):
        self.requests.append((method, params))
        if method == "account/read":
            return {"account": {"type": "chatgpt", "planType": "synthetic"}}
        if method == "thread/start":
            assert params["sandbox"] == "read-only" and params["approvalPolicy"] == "never"
            assert params["ephemeral"] and len(params["dynamicTools"]) == 1
            return {"thread": {"id": "synthetic-cli-thread"}}
        if method == "turn/start":
            assert params["sandboxPolicy"]["access"]["readableRoots"] == [self.temp.name]
            return {"turn": {"id": "synthetic-cli-turn"}}
        raise AssertionError(method)

    def send(self, data):
        self.sent.append(data)

    def close(self):
        self.closed = True


@pytest.fixture
def runtime(monkeypatch):
    FakeRPC.scripts, FakeRPC.clients = [], []
    monkeypatch.setattr(codex, "RPC", FakeRPC)
    monkeypatch.setattr(codex.shutil, "which", lambda _: "synthetic-codex")
    settings.update({"brain_enabled": True, "brain_transport": "cli_only", "connected": ["codex"]})
    return FakeRPC


def test_codex_chat_read_and_request_replay(runtime):
    runtime.scripts = [[tool(), delta(), complete()]]
    result = conversations.submit("cli-thread", "cli-read", "合成時刻を取得")
    assert result["status"] == "completed" and result["reply"] == "合成CLI応答"
    assert result["model_route"]["transport"] == "cli"
    assert result["used_tools"][0]["name"] == "get_current_time"
    again = conversations.submit("cli-thread", "cli-read", "合成時刻を取得")
    assert again["reply"] == result["reply"] and len(runtime.clients) == 1
    assert runtime.clients[0].closed
    with db.get_connection() as connection:
        assert connection.execute("SELECT count(*) FROM turn_events WHERE type='external_session'").fetchone()[0] == 1


def test_codex_approval_resume_and_receipt_only_once(runtime):
    runtime.scripts = [[tool("add_schedule", {"title": "CLI合成予定", "start_time": "2026-10-29T19:00:00+09:00"})],
                       [delta("保存結果を確認しました。"), complete()]]
    result = conversations.submit("cli-thread", "cli-approval", "合成予定を追加")
    assert result["status"] == "waiting_approval"
    with db.get_connection() as connection:
        assert connection.execute("SELECT count(*) FROM calendar_events_cache").fetchone()[0] == 0
    approval_id = store.approvals("cli-approval")[0]["approval_id"]
    approved = conversations.decide(approval_id, True)
    assert approved["status"] == "completed"
    assert conversations.decide(approval_id, True)["reply"] == approved["reply"]
    assert len(runtime.clients) == 2 and all(c.closed for c in runtime.clients)
    prompt = next(p["input"][0]["text"] for method, p in runtime.clients[1].requests if method == "turn/start")
    assert "CLI合成予定" in prompt and "再実行しない" in prompt
    with db.get_connection() as connection:
        assert connection.execute("SELECT count(*) FROM calendar_events_cache WHERE title='CLI合成予定'").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM effect_receipts").fetchone()[0] == 1


def test_codex_repeated_tool_call_is_not_executed_twice(runtime):
    call = tool("save_memory", {"content": "CLI合成記憶"})
    repeated = {**call, "id": 701}
    runtime.scripts = [[call, repeated, delta(), complete()]]
    result = conversations.submit("cli-thread", "cli-repeat", "合成記憶を保存")
    assert result["status"] == "completed" and len(result["used_tools"]) == 1
    assert runtime.clients[0].sent[0]["result"] == runtime.clients[0].sent[1]["result"]
    with db.get_connection() as connection:
        assert connection.execute("SELECT count(*) FROM effect_receipts").fetchone()[0] == 1


@pytest.mark.parametrize("call", [tool("nonexistent_tool"), tool(threadId="another-thread"), tool(tool="shell")])
def test_codex_rejects_unknown_tool_and_other_thread(runtime, call):
    runtime.scripts = [[call, delta(), complete()]]
    result = conversations.submit("cli-thread", "cli-rejected", "合成入力")
    assert result["status"] == "completed" and not result["used_tools"]
    assert runtime.clients[0].sent[0]["result"]["success"] is False


def test_codex_denies_builtin_approval(runtime):
    runtime.scripts = [[{"id": 70, "method": "item/commandExecution/requestApproval", "params": {}}, delta(), complete()]]
    result = conversations.submit("cli-thread", "cli-builtin", "合成入力")
    assert result["status"] == "completed"
    assert runtime.clients[0].sent[0]["error"]["message"] == "PETIT tools only"


@pytest.mark.parametrize("event", [complete("failed"), complete("interrupted"), {"_closed": True}])
def test_codex_failure_closes_client_without_api_fallback(runtime, event):
    runtime.scripts = [[delta(), event]]
    result = conversations.submit("cli-thread", "cli-failure", "合成入力")
    assert result["status"] == "failed" and len(runtime.clients) == 1
    assert runtime.clients[0].closed


def test_codex_cancel_closes_client(runtime, monkeypatch):
    original = FakeRPC.request
    def request(self, method, params=None, **kwargs):
        result = original(self, method, params, **kwargs)
        if method == "turn/start":
            with db.get_connection() as connection:
                connection.execute("UPDATE turns SET cancel_requested=1 WHERE request_id='cli-cancel'")
        return result
    monkeypatch.setattr(FakeRPC, "request", request)
    runtime.scripts = [[]]
    result = conversations.submit("cli-thread", "cli-cancel", "合成入力")
    assert result["status"] == "cancelled" and runtime.clients[0].closed


def test_cli_only_never_falls_back_to_sdk_or_api(monkeypatch):
    configure_priority(monkeypatch)
    settings.update({"brain_transport": "cli_only"})
    seen = []
    def run(*args, **kwargs):
        seen.append(priority.current()["profile"])
        raise brain.lmstudio_client.LMStudioError("synthetic failure")
    with pytest.raises(brain.lmstudio_client.LMStudioError, match="CLI Brain"):
        priority.run("request", run)
    assert seen == ["codex"]
    store.create_thread("private-thread", privacy="local_only")
    store.accept("private-thread", "private-cli", {"message": "private"}); store.claim("private-cli")
    with pytest.raises(brain.lmstudio_client.LMStudioError):
        priority.run("private-cli", run)
    assert seen == ["codex"]


def test_cli_only_blocks_images_before_vision(runtime, monkeypatch):
    from backend import vision
    analyze = Mock()
    monkeypatch.setattr(vision, "analyze", analyze)
    result = conversations.submit("cli-thread", "cli-image", "合成画像", attachment_ids=["synthetic"])
    assert result["status"] == "failed" and "画像付き会話は未対応" in result["error"]
    analyze.assert_not_called()
    assert not runtime.clients


def test_cli_transport_setting_and_diagnostics_require_admin(client, monkeypatch):
    assert client.post("/api/setup/codex/diagnose").status_code == 401
    admin(client)
    assert client.put("/api/setup/config", json={"brain_transport": "invalid"}).status_code == 422
    assert client.put("/api/setup/config", json={"brain_transport": "cli_only"}).status_code == 200
    monkeypatch.setattr(codex, "RPC", Mock(side_effect=PermissionError("SECRET-PATH")))
    monkeypatch.setattr(codex.shutil, "which", lambda _: "synthetic-codex")
    result = client.post("/api/setup/codex/diagnose").json()
    assert result["authenticated"] is None and result["inference"] == "unknown"
    assert "SECRET-PATH" not in json.dumps(result) and "権限" in result["error"]


def test_codex_status_is_passive(monkeypatch):
    rpc = Mock()
    monkeypatch.setattr(codex, "RPC", rpc)
    assert codex.status()["authenticated"] is None
    rpc.assert_not_called()


def test_codex_completed_item_can_supply_final_answer(runtime):
    runtime.scripts = [[delta("途中経過"), {"method": "item/completed", "params": {
        "item": {"type": "agentMessage", "phase": "final_answer", "text": "最終返答"}}}, complete()]]
    result = conversations.submit("cli-thread", "cli-final", "合成入力")
    assert result["reply"] == "最終返答"


def test_codex_call_id_reuse_with_changed_arguments_fails(runtime):
    first = tool()
    changed = tool("get_tasks", ident=701, callId=first["params"]["callId"])
    runtime.scripts = [[first, changed, complete()]]
    result = conversations.submit("cli-thread", "cli-collision", "合成入力")
    assert result["status"] == "failed" and "再使用" in result["error"]
    assert runtime.clients[0].closed and len(runtime.clients[0].sent) == 1


def test_codex_deadline_closes_client(runtime, monkeypatch):
    clock = iter([0, 0, 181])
    monkeypatch.setattr(codex.time, "monotonic", lambda: next(clock, 181))
    runtime.scripts = [[]]
    result = conversations.submit("cli-thread", "cli-timeout", "合成入力")
    assert result["status"] == "failed" and runtime.clients[0].closed


def test_cli_only_cannot_be_enabled_with_only_sdk_connected(client, monkeypatch):
    admin(client)
    settings.update({"connected": ["antigravity"], "antigravity_model": "synthetic"})
    monkeypatch.setattr("backend.antigravity_brain.installed", lambda: True)
    response = client.put("/api/setup/config", json={"brain_transport": "cli_only", "brain_enabled": True})
    assert response.status_code == 400 and settings.load()["brain_transport"] == "mixed"


def test_unavailable_cli_brain_can_be_disabled(client):
    admin(client)
    settings.update({"brain_enabled": True, "brain_transport": "cli_only", "connected": []})
    response = client.put("/api/setup/config", json={"brain_transport": "cli_only", "brain_enabled": False})
    assert response.status_code == 200 and settings.load()["brain_enabled"] is False
