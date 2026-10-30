"""Retirement and provider-neutral Core boundary contracts; synthetic data only."""
import json
from unittest.mock import Mock
import pytest
from backend import provider_runtime as runtime, model_routing, setup_store as settings
from tests.test_setup_integrations import isolated, client, admin
from backend import brain, brain_priority, external_brain, conversation_api as api, conversation_store as store, db, request_context


def test_legacy_selection_survives_and_never_falls_back(tmp_path, monkeypatch):
    path = tmp_path / "routing.json"
    original = '{"chat":"antigravity_sdk","agent":"local"}'
    path.write_text(original)
    monkeypatch.setattr(model_routing, "STATE_PATH", path)
    status = model_routing.public_status()
    assert status["selections"]["chat"] == "antigravity_sdk"
    assert not status["routes"]["chat"]["active"]["configured"]
    assert "antigravity_sdk" not in [x["profile"] for x in status["routes"]["chat"]["options"]]
    with pytest.raises(model_routing.ModelRoutingError, match="廃止"):
        model_routing.endpoint("chat")
    assert path.read_text() == original


def test_sdk_priority_requires_explicit_reselection(monkeypatch):
    settings.update({"brain_enabled": True, "priority": ["antigravity", "codex", "deepseek"],
                     "connected": ["antigravity", "codex"]}, {"antigravity_key": "synthetic-retained"})
    execute = Mock()
    with pytest.raises(brain.lmstudio_client.LMStudioError, match="廃止"):
        brain_priority.run("unused", execute)
    execute.assert_not_called()
    assert settings.load()["secrets"]["antigravity_key"] == "synthetic-retained"


def test_retired_sdk_endpoints_do_not_start_or_delete(client):
    admin(client)
    for op in ("connect", "test"):
        assert client.post("/api/setup/services/antigravity/" + op).status_code == 409
    assert client.put("/api/setup/config", json={"priority": ["codex", "deepseek"]}).status_code == 200


@pytest.mark.parametrize("raw", ['{"extra":1}', '{"count":true}', '{"count":NaN}', '[]', '{"count":0}'])
def test_common_validator_keeps_strict_sdk_boundary(raw):
    with pytest.raises(ValueError):
        runtime.validate_arguments({"type":"object", "properties":{"count":{"type":"integer", "minimum":1}}, "required":["count"]}, raw)


def test_bridge_approval_receipt_and_resume(monkeypatch):
    target = {"provider":"codex", "profile":"codex", "model":"synthetic", "base_url":""}
    monkeypatch.setattr(brain, "check_provider", lambda thread: target)
    def run(request_id, **kwargs):
        used = list(kwargs.get("used_tools") or [])
        if kwargs.get("messages") is not None:
            return external_brain.finish(request_id, "保存結果を確認しました", used, target)
        external_brain.tool_bridge(request_id, target, used)("add_schedule", '{"title":"合成予定","start_time":"2026-10-30T12:00:00+09:00"}')
        return external_brain.finish(request_id, "", used, target)
    monkeypatch.setattr(brain, "run", run)
    pending = api.submit("bridge-thread", "bridge-request", "合成予定を追加", is_admin=True)
    assert pending["status"] == "waiting_approval"
    approved = api.decide(store.approvals("bridge-request")[0]["approval_id"], True)
    assert approved["status"] == "completed"
    assert api.submit("bridge-thread", "bridge-request", "合成予定を追加")["reply"] == approved["reply"]
    with db.get_connection() as c:
        assert c.execute("SELECT count(*) FROM effect_receipts WHERE request_id='bridge-request'").fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM calendar_events_cache WHERE title='合成予定'").fetchone()[0] == 1


def test_bridge_rechecks_live_guest_permission(monkeypatch):
    store.create_thread("guest-thread"); store.accept("guest-thread", "guest-request", {"message":"hello"}); store.claim("guest-request")
    target = {"provider":"codex"}
    monkeypatch.setattr(brain, "check_provider", lambda thread: target)
    with request_context.bind(request_id="guest-request", session_id="guest-thread", is_admin=False):
        with pytest.raises(ValueError):
            external_brain.tool_bridge("guest-request", target, [])("get_current_time", "{}")
