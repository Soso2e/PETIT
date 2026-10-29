"""Offline contracts only. No Google login, monthly quota or live CLI proof."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from unittest.mock import Mock, patch

import pytest

from backend import antigravity_cli as cli, brain, brain_priority, conversation_store as store, db, model_routing
from scripts import probe_antigravity_cli as probe
from tests.test_setup_integrations import isolated, client, admin  # isolated Core/settings, no service startup

CID = "055a398f-db14-4c5f-abbb-1bf03f8120a7"
OTHER = "9ec58bfd-4d67-4f5e-83a5-9d907e9c6b1f"


def envelope(**values):
    return {"conversation_id": CID, "status": "SUCCESS", "response": "合成応答", **values}


def lines(cid=CID):
    return [json.dumps(x) for x in [
        {"event": "init", "conversation_id": cid, "init": {"permission_mode": "request-review"}},
        {"event": "step_update", "step_update": {"conversation_id": cid, "step_index": 2,
            "state": "ACTIVE", "step_type": "agent_response", "text_delta": "合成"}},
        {"event": "step_update", "step_update": {"conversation_id": cid, "step_index": 3,
            "state": "DONE", "step_type": "tool", "tool_name": "read_file",
            "tool_info": {"parameters": {"secret": "DO-NOT-STORE"}, "output": "DO-NOT-STORE"}}},
        {"event": "result", "result": envelope(conversation_id=cid, usage={"input_tokens": 14, "output_tokens": 3})},
    ]]


def accepted(thread="thread-a", request="request-a"):
    store.create_thread(thread)
    store.accept(thread, request, {"message": "合成入力"})
    store.claim(request)
    return request


def test_json_and_stream_equivalent_unknown_quota_and_no_raw_tool_data():
    parser = cli.Protocol()
    parser.feed(json.dumps(envelope(usage={"input_tokens": 14, "output_tokens": 3})))
    stream = cli.Protocol()
    observed = [stream.feed(line) for line in lines()]
    assert stream.finish() == parser.finish()
    assert observed[1]["text_delta"] == "合成"
    assert observed[2]["tool"] == "read_file"
    assert "DO-NOT-STORE" not in json.dumps(observed)
    assert stream.finish()["quota_remaining"] == "unknown"


@pytest.mark.parametrize("raw", ['[]', 'null', '{"status":"SUCCESS"}', '{"event":"alien"}',
    '{"status":"SUCCESS","conversation_id":"bad"}', '{"status": "PENDING"}',
    '{"event":"step_update","step_update":{}}', '{"status":"SUCCESS","usage":{"total_tokens":NaN}}'])
def test_malformed_output_fails_closed(raw):
    with pytest.raises(ValueError):
        cli.Protocol().feed(raw)


def test_truncation_duplicate_result_and_limits():
    parser = cli.Protocol()
    parser.feed(lines()[0])
    with pytest.raises(ValueError, match="missing_cli_result"):
        parser.finish()
    parser.feed(lines()[-1])
    with pytest.raises(ValueError, match="event_after_result"):
        parser.feed(lines()[-1])
    with patch.object(cli, "MAX_BYTES", 10), pytest.raises(ValueError, match="output_limit"):
        cli.Protocol().feed(lines()[0])
    with patch.object(cli, "MAX_EVENTS", 1), pytest.raises(ValueError, match="output_limit"):
        parser = cli.Protocol(); parser.feed(lines()[0]); parser.feed(lines()[1])


@pytest.mark.parametrize("raw,reason", [("429 RESOURCE_EXHAUSTED SECRET", "usage_limit"),
    ("authentication required SECRET", "authentication_required"), ("permission denied SECRET", "permission_denied"),
    ("timeout SECRET", "timeout"), ("cancelled SECRET", "cancelled")])
def test_errors_are_classified_and_redacted(raw, reason):
    parser = cli.Protocol()
    parser.feed(json.dumps(envelope(status="ERROR", error=raw, response="SECRET")))
    result = parser.finish()
    assert result["error"] == reason
    assert "SECRET" not in json.dumps(result)


def test_usage_is_tokens_never_remaining_subscription_quota():
    parser = cli.Protocol()
    result = parser.feed(json.dumps(envelope(usage={"total_tokens": 17, "input_tokens": -1,
        "thinking_tokens": True, "output_tokens": "bad", "quota_remaining": 999})))
    assert result["usage"] == {"total_tokens": 17}
    assert result["quota_remaining"] == "unknown"


def test_fixture_restart_thread_isolation_progress_and_no_tools_executed():
    request = accepted()
    with patch("backend.tools.dispatch", side_effect=AssertionError("must not execute")):
        result = cli.replay_fixture(request, lines())
    assert result["evidence"] == "mock_only" and not result["live_verified"]
    assert cli.fixture_session("thread-a") == CID
    assert cli.fixture_session("thread-b") is None
    snapshot = store.snapshot("thread-a")
    assert len([x for x in snapshot["events"] if x["type"] == "antigravity_cli_mock_progress"]) == 2
    assert "DO-NOT-STORE" not in json.dumps(snapshot)
    with pytest.raises(ValueError, match="already_started"):
        cli.replay_fixture(request, lines())
    # Restore mapping after a new Core lookup; do not re-run an interrupted request.
    store.finish(request, {"reply": "", "evidence": "mock_only"}, status="failed")
    accepted(request="request-b")
    assert cli.replay_fixture("request-b", lines())["conversation_id"] == CID
    accepted(thread="thread-b", request="request-c")
    with pytest.raises(ValueError, match="owned_by_other_thread"):
        cli.replay_fixture("request-c", lines())
    assert cli.fixture_session("thread-b") is None
    accepted(thread="thread-c", request="request-d")
    assert cli.replay_fixture("request-d", lines(OTHER))["conversation_id"] == OTHER


def test_resume_mismatch_and_cancel_timeout_never_resume_partial_work():
    request = accepted()
    with db.get_connection() as c:
        c.execute("UPDATE turns SET cancel_requested=1 WHERE request_id=?", (request,))
    with pytest.raises(ValueError, match="cancelled"):
        cli.replay_fixture(request, lines())
    with pytest.raises(ValueError, match="already_started"):
        cli.replay_fixture(request, lines())
    accepted(thread="timeout", request="timeout")
    clock = iter([0, 6])
    with pytest.raises(TimeoutError):
        cli.replay_fixture("timeout", lines(), now=lambda: next(clock))
    parser = cli.Protocol(CID)
    with pytest.raises(ValueError, match="conversation_mismatch"):
        parser.feed(lines(OTHER)[0])


def test_config_api_detects_without_spawning_and_cannot_enable(client):
    assert client.get("/api/setup/antigravity-cli").status_code == 401
    admin(client)
    with patch.object(cli, "executable", return_value="synthetic-agy"), patch.object(subprocess, "Popen", side_effect=AssertionError("no process")):
        response = client.get("/api/setup/antigravity-cli")
        assert response.status_code == 200 and response.json()["installed"]
        assert response.json()["authentication"] == "unknown"
        assert not response.json()["production_enabled"]
        for operation in ("connect", "test"):
            assert client.post("/api/setup/services/antigravity_cli/" + operation).status_code == 409
        response = client.put("/api/setup/config", json={"priority": ["antigravity_cli", "codex", "deepseek"]})
        assert response.status_code == 422


def test_explicit_cli_never_defaults_or_falls_back_to_another_provider(tmp_path, monkeypatch):
    with patch.dict("os.environ", {"PETIT_CHAT_PROFILE": "antigravity_cli"}), pytest.raises(model_routing.ModelRoutingError):
        model_routing._default_profile("chat")
    selection = tmp_path / "route.json"
    selection.write_text('{"chat":"antigravity_cli"}', encoding="utf-8")
    with patch.object(model_routing, "STATE_PATH", selection), pytest.raises(model_routing.ModelRoutingError):
        model_routing._read_selection()
    with patch.object(brain.lmstudio_client, "endpoint", return_value={"provider": "antigravity_cli"}), pytest.raises(brain.lmstudio_client.LMStudioError):
        brain.check_provider({"privacy": "standard"})
    with patch.object(brain_priority.settings, "load", return_value={"priority": ["antigravity_cli", "antigravity"]}), pytest.raises(brain.lmstudio_client.LMStudioError):
        brain_priority.run("request", Mock(side_effect=AssertionError("no fallback")))
    with pytest.raises(ValueError):
        brain_priority.target("antigravity_cli")
    with patch.dict("os.environ", {"PETIT_ALLOW_ANTIGRAVITY_CLI": "true"}), pytest.raises(ValueError):
        cli.require_production_permission()


def test_missing_cli_report_is_skipped_without_model_or_auth_claim():
    with patch.object(probe, "executable", return_value=None), patch.object(probe, "invoke") as invoke:
        report = probe.run(live=True)
    invoke.assert_not_called()
    assert report["status"] == "skipped" and not report["network_invoked"]
    assert report["subscription_quota_used"] == "unknown" and report["model"] == "unknown"
    assert not report["petit_integration_verified"]


def test_direct_live_probe_uses_explicit_conversation_and_reports_only_observations():
    read_events = [json.loads(line) for line in lines()]
    read_events[-1]["result"]["response"] = "READ_EVIDENCE_4f99"
    answers = [(0, "agy 1.4.2", ""), (0, json.dumps(envelope()), ""),
               (0, "\n".join(json.dumps(event) for event in read_events), ""), (0, json.dumps(envelope()), "")]
    with patch.object(probe, "executable", return_value="synthetic-agy"), patch.object(probe, "invoke", side_effect=answers) as invoke:
        report = probe.run(live=True)
    assert report["status"] == "completed"
    assert report["version"] == "1.4.2" and report["subscription_quota_used"] == "unknown"
    assert report["authentication"] == "official_cli_managed_unknown_account_type"
    assert not report["petit_integration_verified"]
    assert invoke.call_count == 4
    for call in invoke.call_args_list[2:]:
        command = call.args[0]
        assert command[command.index("--conversation") + 1] == CID
    for call in invoke.call_args_list[1:]:
        command = call.args[0]
        assert command[command.index("--mode=plan")] == "--mode=plan"
        assert "--sandbox" in command
        assert "--continue" not in command and "--dangerously-skip-permissions" not in command
    assert "書き込み" in invoke.call_args_list[2].args[0][2]


def test_direct_live_probe_fails_if_read_tool_missing_or_unsafe_tool_observed():
    events = [json.loads(line) for line in lines()]
    events[2]["step_update"]["tool_name"] = "run_command"
    events[-1]["result"]["response"] = "READ_EVIDENCE_4f99"
    answers = [(0, "agy 1.4.2", ""), (0, json.dumps(envelope()), ""),
               (0, "\n".join(json.dumps(event) for event in events), "")]
    with patch.object(probe, "executable", return_value="synthetic-agy"), patch.object(probe, "invoke", side_effect=answers):
        report = probe.run(live=True)
    assert report["status"] == "failed"
    assert report["checks"][-1]["unsafe_tool_observed"]


def test_direct_version_only_and_raw_probe_errors_are_not_reported():
    with patch.object(probe, "executable", return_value="synthetic-agy"), patch.object(probe, "invoke", return_value=(0, "agy 1.4.2", "SECRET")) as invoke:
        report = probe.run()
    assert invoke.call_count == 1 and not report["network_invoked"]
    assert "SECRET" not in json.dumps(report)
    with patch.object(probe, "executable", return_value="synthetic-agy"), patch.object(probe, "invoke", side_effect=[(0,"1.4.2",""), (1,"garbled SECRET","authentication required SECRET")]):
        report = probe.run(live=True)
    assert report["status"] == "failed" and report["checks"][0]["reason"] == "authentication_required"
    assert "SECRET" not in json.dumps(report)


@pytest.mark.parametrize("cancel,timeout,error", [(lambda: True, 5, InterruptedError), (lambda: False, .08, TimeoutError)])
def test_owned_real_subprocess_is_stopped_on_cancel_or_timeout(tmp_path, cancel, timeout, error):
    real_popen = subprocess.Popen
    created = []
    def start(*args, **kwargs):
        process = real_popen(*args, **kwargs); created.append(process); return process
    with patch.object(subprocess, "Popen", side_effect=start), pytest.raises(error):
        probe.invoke([sys.executable, "-c", "import time; time.sleep(10)"], tmp_path, timeout=timeout, cancel=cancel)
    assert created and created[0].poll() is not None


def test_direct_probe_strips_api_auth_and_bounds_output(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-secret")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "synthetic-path")
    code, output, _ = probe.invoke([sys.executable, "-c",
        "import os; print(os.getenv('GEMINI_API_KEY')); print(os.getenv('GOOGLE_APPLICATION_CREDENTIALS'))"], tmp_path)
    assert code == 0 and output.splitlines() == ["None", "None"]
    with patch.object(probe, "MAX_BYTES", 100), pytest.raises(ValueError, match="output_limit"):
        probe.invoke([sys.executable, "-c", "print('x'*1000)"], tmp_path)


def test_real_grandchild_stops_with_owned_process_tree(tmp_path):
    # A heartbeat proves the child was running before cancellation and stopped
    # afterwards. This tests OS cleanup with synthetic processes, never agy.
    heartbeat = tmp_path / "heartbeat"
    pidfile = tmp_path / "child-pid"
    child_code = ("import pathlib,time; p=pathlib.Path(" + repr(str(heartbeat)) + "); "
                  "\nwhile True:\n p.write_text(str(time.time())); time.sleep(.02)")
    parent_code = ("import pathlib,subprocess,sys,time; "
                   "p=subprocess.Popen([sys.executable,'-c'," + repr(child_code) + "]); "
                   "pathlib.Path(" + repr(str(pidfile)) + ").write_text(str(p.pid)); time.sleep(10)")
    try:
        with pytest.raises(InterruptedError):
            probe.invoke([sys.executable, "-c", parent_code], tmp_path, timeout=4,
                         cancel=lambda: heartbeat.exists() and heartbeat.stat().st_size > 0)
        time.sleep(.08)
        after = heartbeat.read_text()
        time.sleep(.12)
        assert heartbeat.read_text() == after
    finally:
        # Only clean up a still-writing child in case the assertion failed.
        if pidfile.exists() and heartbeat.exists():
            before = heartbeat.read_text()
            time.sleep(.06)
            if heartbeat.read_text() != before:
                import os
                import signal
                os.kill(int(pidfile.read_text()), signal.SIGTERM)
