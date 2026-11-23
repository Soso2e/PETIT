"""Structured CLI adapter/Core contracts. No real account or cloud inference."""
import json
import sys
import time
from unittest.mock import Mock

import pytest

from backend import antigravity_cli as cli, antigravity_cli_brain as runtime, brain, db
from backend import setup_store as settings, conversation_api as conversations, conversation_store as store
from tests.test_setup_integrations import isolated, client, admin

CID = "055a398f-db14-4c5f-abbb-1bf03f8120a7"


def output(content="合成CLI応答", calls=None):
    return 0, json.dumps({"event": "result", "result": {"status": "SUCCESS", "conversation_id": CID,
        "response": json.dumps({"content": content, "tool_calls": calls or []}, ensure_ascii=False),
        "usage": {"total_tokens": 5}}}), ""


@pytest.fixture
def selected(monkeypatch):
    monkeypatch.setattr(cli, "executable", lambda: "synthetic-agy")
    settings.update({"brain_enabled": True, "brain_transport": "cli_only", "antigravity_cli_enabled": True,
        "connected": ["antigravity_cli"], "priority": ["antigravity_cli", "codex", "antigravity", "deepseek"]})


def test_cli_chat_and_replay(selected, monkeypatch):
    invoke = Mock(return_value=output())
    monkeypatch.setattr(runtime, "invoke", invoke)
    result = conversations.submit("thread", "hello", "合成入力")
    assert result["status"] == "completed" and result["reply"] == "合成CLI応答"
    assert result["model_route"]["provider"] == "antigravity_cli"
    assert conversations.submit("thread", "hello", "合成入力")["reply"] == result["reply"]
    assert invoke.call_count == 1
    command = invoke.call_args.args[0]
    assert "--agent" in command and "--sandbox" in command and "--mode=plan" in command
    assert command[command.index("--settings") + 1] == '{"permissions":{"deny":["command(*)"]}}'
    assert "合成入力" not in " ".join(command) and "--dangerously-skip-permissions" not in command
    with db.get_connection() as connection:
        assert connection.execute("SELECT count(*) FROM turn_events WHERE type='antigravity_cli_step'").fetchone()[0] == 1


def test_cli_read_and_approved_write_resume(selected, monkeypatch):
    invoke = Mock(side_effect=[output(calls=[{"name": "get_current_time", "arguments": {}}]),
        output(calls=[{"name": "add_schedule", "arguments": {"title": "CLI予定", "start_time": "2026-10-29T21:00:00+09:00"}}]),
        output("保存結果を確認しました")])
    monkeypatch.setattr(runtime, "invoke", invoke)
    result = conversations.submit("thread", "write", "合成予定を追加", is_admin=True)
    assert result["status"] == "waiting_approval"
    with db.get_connection() as connection:
        assert connection.execute("SELECT count(*) FROM calendar_events_cache").fetchone()[0] == 0
    approval = store.approvals("write")[0]["approval_id"]
    done = conversations.decide(approval, True)
    assert done["status"] == "completed"
    assert conversations.decide(approval, True)["reply"] == done["reply"]
    assert invoke.call_count == 3
    assert "CLI予定" in invoke.call_args.args[2]
    with db.get_connection() as connection:
        assert connection.execute("SELECT count(*) FROM effect_receipts").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM calendar_events_cache").fetchone()[0] == 1


@pytest.mark.parametrize("raw", ["[]", "null", "{}", '{"content":1,"tool_calls":[]}',
    '{"content":"","tool_calls":[{"name":"shell","arguments":{}}]}',
    '{"content":"","tool_calls":[{"name":"get_current_time","arguments":[]}]}',
    '{"content":"a","tool_calls":[]}\n{"content":"b","tool_calls":[]}',
    '{"content":"a","tool_calls":[],"extra":true}'])
def test_invalid_response_cannot_execute_tools(raw):
    with pytest.raises(runtime.CLIError):
        runtime.parse_response(raw, brain.schemas())


def test_secrets_are_not_in_child_environment(monkeypatch):
    for key in ["PETIT_BOOTSTRAP_TOKEN", "DEEPSEEK_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS", "ACCESS_TOKEN"]:
        monkeypatch.setenv(key, "SYNTHETIC-SECRET")
    assert "SYNTHETIC-SECRET" not in json.dumps(runtime.environment())


def test_windows_runtime_env_keys_are_preserved(monkeypatch):
    expected = {
        "PATHEXT": ".COM;.EXE;.BAT;.CMD",
        "ComSpec": r"C:\WINDOWS\system32\cmd.exe",
        "SystemDrive": "C:",
        "OS": "Windows_NT",
        "NUMBER_OF_PROCESSORS": "8",
        "PROCESSOR_ARCHITECTURE": "AMD64",
        "CommonProgramFiles": r"C:\Program Files\Common Files",
        "CommonProgramFiles(x86)": r"C:\Program Files (x86)\Common Files",
        "CommonProgramW6432": r"C:\Program Files\Common Files",
        "ProgramW6432": r"C:\Program Files",
        "HOMEDRIVE": "C:",
        "HOMEPATH": r"\Users\synthetic",
    }
    for key, value in expected.items():
        monkeypatch.setenv(key, value)
    env = {k.upper(): v for k, v in runtime.environment().items()}
    for key, value in expected.items():
        assert env[key.upper()] == value


def test_cli_cancel_before_start(selected, monkeypatch):
    store.create_thread("thread");store.accept("thread", "cancel", {"message": "合成"})
    with db.get_connection() as connection:
        connection.execute("UPDATE turns SET cancel_requested=1 WHERE request_id='cancel'")
    invoke = Mock();monkeypatch.setattr(runtime, "invoke", invoke)
    assert conversations.process("cancel")["status"] == "cancelled"
    invoke.assert_not_called()


def test_cli_connect_is_explicit_and_disconnect_stops_permission(client, monkeypatch):
    admin(client)
    monkeypatch.setattr(cli, "executable", lambda: "synthetic-agy")
    assert client.post("/api/setup/services/antigravity_cli/connect").status_code == 200
    assert settings.load()["priority"][0] == "antigravity_cli"
    cli.require_production_permission()
    assert client.get("/api/setup/antigravity-cli").json()["production_enabled"]
    assert client.post("/api/setup/services/antigravity_cli/disconnect").status_code == 200
    with pytest.raises(ValueError):cli.require_production_permission()


def test_bounded_transport_times_out_and_reaps_owned_process(tmp_path):
    started=time.monotonic()
    with pytest.raises(runtime.CLIError, match="タイムアウト"):
        runtime.invoke([sys.executable,"-c","import time; time.sleep(30)"],tmp_path,"synthetic",lambda:None,timeout=.15)
    assert time.monotonic()-started < 10


def test_transport_cleans_child_after_parent_exits(tmp_path):
    marker=tmp_path/"heartbeat.txt"
    child="import time; from pathlib import Path; p=Path("+repr(str(marker))+"); "+"\nfor n in range(200):\n p.write_text(str(n)); time.sleep(.02)"
    parent="import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',"+repr(child)+"]); time.sleep(.5)"
    code,_,_=runtime.invoke([sys.executable,"-c",parent],tmp_path,"synthetic",lambda:None,timeout=5)
    assert code==0 and marker.exists()
    first=marker.read_text();time.sleep(.25)
    assert marker.read_text()==first


@pytest.mark.parametrize("reason", ["invalid_cli_response", "timeout", "authentication_required"])
def test_setup_failure_reports_safe_reason_and_persists_it(client, selected, monkeypatch, reason):
    admin(client)
    monkeypatch.setattr(runtime, "invoke", Mock(side_effect=runtime.CLIError(reason, "PRIVATE-DIAGNOSTIC")))
    response=client.post("/api/setup/services/antigravity_cli/test")
    assert response.status_code==400 and response.json()["reason"]==reason
    assert "PRIVATE-DIAGNOSTIC" not in response.text
    with db.get_connection() as connection:
        row=connection.execute("SELECT result_json FROM turns WHERE request_id LIKE 'setup-test-%' ORDER BY updated_at DESC LIMIT 1").fetchone()
    assert json.loads(row[0])["reason"]==reason


def test_invoke_popen_oserror_reports_cli_start_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.subprocess, "Popen", Mock(side_effect=FileNotFoundError(2, "missing")))
    with pytest.raises(runtime.CLIError) as exc:
        runtime.invoke(["missing-agy"], tmp_path, "synthetic", lambda: None)
    assert exc.value.reason == "cli_start_failed"


def test_completion_post_start_oserror_reports_cli_io_error(monkeypatch):
    monkeypatch.setattr(runtime.cli, "executable", lambda: "agy")
    monkeypatch.setattr(runtime, "invoke", Mock(side_effect=PermissionError(13, "locked")))
    with pytest.raises(runtime.CLIError) as exc:
        runtime.completion({"model": "gemini-3.8-flash-medium"}, [{"role": "user", "content": "hi"}], [], lambda: None)
    assert exc.value.reason == "cli_io_error"


def test_parse_response_unwraps_nested_json_content():
    inner = json.dumps({"content": "作業セッションの確認を行いました。", "tool_calls": []}, ensure_ascii=False)
    outer = json.dumps({"content": inner, "tool_calls": []}, ensure_ascii=False)
    parsed = runtime.parse_response(outer, brain.schemas())
    assert parsed["content"] == "作業セッションの確認を行いました。"
    assert parsed["tool_calls"] == []
