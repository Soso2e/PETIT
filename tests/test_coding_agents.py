"""Protocol lifecycle checks; synthetic RPC only, no actual Codex inference."""
import json
from unittest.mock import Mock
import pytest

from backend import coding_agents, codex_brain
from tests.test_codex_brain import FakeRPC, delta, complete, tool


def test_codex_coding_bridge_and_cleanup(monkeypatch):
    FakeRPC.clients=[]
    FakeRPC.scripts=[[tool("list_files",tool="petit_coding_tool"),delta("変更内容と未確認事項"),complete()]]
    monkeypatch.setattr(codex_brain,"RPC",FakeRPC)
    invoke=Mock(return_value={"files":["answer.py"]})
    result=coding_agents.run("codex",{"model":"gpt-6.1-sol", "effort":"high"},"合成開発",invoke,lambda:None,lambda kind:None)
    assert result == "変更内容と未確認事項" and FakeRPC.clients[0].closed
    invoke.assert_called_once_with("list_files",{})
    params=next(p for method,p in FakeRPC.clients[0].requests if method=="thread/start")
    assert params["dynamicTools"][0]["name"] == "petit_coding_tool"
    assert params["model"] == "gpt-6.1-sol"
    turn = next(p for method, p in FakeRPC.clients[0].requests if method == "turn/start")
    assert turn["effort"] == "high"


def test_codex_coding_cancel_closes_client(monkeypatch):
    FakeRPC.clients=[];FakeRPC.scripts=[[]]
    monkeypatch.setattr(codex_brain,"RPC",FakeRPC)
    def check():raise InterruptedError("cancel")
    with pytest.raises(InterruptedError):
        coding_agents.run("codex",{"model":""},"合成開発",Mock(),check,lambda kind:None)
    assert FakeRPC.clients[0].closed


@pytest.mark.parametrize("reason", [
    "timeout", "invalid_cli_response", "cli_start_transient", "temporarily_unavailable", "cli_incomplete",
])
def test_antigravity_coding_retries_model_step_without_replaying_tools(monkeypatch, reason):
    responses = iter([
        ({"role":"assistant","content":"","tool_calls":[{"id":"call","type":"function","function":{"name":"list_files","arguments":"{}"}}]}, {}),
        coding_agents.antigravity_cli_brain.CLIError(reason, "synthetic failure"),
        ({"role":"assistant","content":"完了候補です。実テスト未実施。","tool_calls":[]}, {}),
    ])
    captured=[]
    def completion(target,messages,catalog,check,*,on_progress):
        captured.append(list(messages))
        assert {x["function"]["name"] for x in catalog} == {"list_files","read_file","write_file","run_static_checks"}
        on_progress("cli_initialized")
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response
    monkeypatch.setattr(coding_agents.antigravity_cli_brain,"completion",completion)
    invoke = Mock(return_value={"files":["answer.py"]})
    progress = Mock()
    result = coding_agents.run("antigravity_cli",{},"合成開発",invoke,lambda:None,progress)
    assert "実テスト未実施" in result and captured[1][-1]["role"] == "tool"
    assert captured[1] == captured[2]
    invoke.assert_called_once_with("list_files", {})
    assert ("model_retry_" + reason,) in [call.args for call in progress.call_args_list]


@pytest.mark.parametrize(("reason", "calls"), [("timeout", 2), ("authentication_required", 1), ("cli_start_failed", 1)])
def test_antigravity_coding_stops_on_unrecoverable_or_repeated_error(monkeypatch, reason, calls):
    error = coding_agents.antigravity_cli_brain.CLIError(reason, "synthetic failure")
    completion = Mock(side_effect=error)
    monkeypatch.setattr(coding_agents.antigravity_cli_brain, "completion", completion)
    invoke = Mock()
    with pytest.raises(coding_agents.antigravity_cli_brain.CLIError, match="synthetic failure"):
        coding_agents.run("antigravity_cli", {}, "合成開発", invoke, lambda: None, lambda kind: None)
    assert completion.call_count == calls
    invoke.assert_not_called()


@pytest.mark.parametrize("status", ["SUCCESS", "ERROR"])
def test_antigravity_git_uses_one_native_turn(monkeypatch, tmp_path, status):
    conversation = "83d75605-0804-4d10-8787-fef77fe44190"
    monkeypatch.setattr(coding_agents.antigravity_cli, "executable", lambda: "agy")
    def invoke(command, workspace, prompt, check, *, timeout, on_line):
        assert workspace == tmp_path
        assert command == ["agy", "--input-format", "stream-json", "--output-format", "stream-json",
                           "--mode=auto", "--model", "gemini-test", "--effort", "medium"]
        assert "合成開発" in prompt
        events = [
            {"event": "init", "conversation_id": conversation, "init": {}},
            {"event": "step_update", "step_update": {
                "conversation_id": conversation, "step_index": 1, "state": "DONE",
                "step_type": "tool", "tool_name": "run_command",
            }},
            {"event": "result", "result": {
                "conversation_id": conversation, "status": status, "response": "確認結果を報告します。",
                "error": "SERVICE UNAVAILABLE" if status == "ERROR" else "",
            }},
        ]
        for event in events:
            on_line(json.dumps(event))
        return (0 if status == "SUCCESS" else 1), "", ""
    launch = Mock(side_effect=invoke)
    monkeypatch.setattr(coding_agents.antigravity_cli_brain, "invoke", launch)
    phases = []
    args = ({"model": "gemini-test", "effort": "medium"}, "合成開発", tmp_path, lambda: None, phases.append)
    if status == "SUCCESS":
        assert coding_agents.run_git("antigravity_cli", *args) == "確認結果を報告します。"
        assert phases == ["model_request", "cli_initialized", "cli_responding", "cli_validating", "model_response"]
    else:
        with pytest.raises(coding_agents.antigravity_cli_brain.CLIError) as exc:
            coding_agents.run_git("antigravity_cli", *args)
        assert exc.value.reason == "temporarily_unavailable"
    launch.assert_called_once()


def test_codex_git_uses_native_workspace_tools(monkeypatch, tmp_path):
    class DevelopmentRPC(FakeRPC):
        def __init__(self, *, workspace, development):
            assert workspace == tmp_path and development
            super().__init__(workspace=workspace)

    FakeRPC.clients = []
    FakeRPC.scripts = [[delta("検査を実施しました。"), complete()]]
    monkeypatch.setattr(codex_brain, "RPC", DevelopmentRPC)
    phases = []
    assert coding_agents.run_git("codex", {"model": "gpt-6.1-sol"}, "目的", tmp_path,
                                 lambda: None, phases.append) == "検査を実施しました。"
    client = FakeRPC.clients[0]
    assert client.closed
    params = next(params for method, params in client.requests if method == "thread/start")
    assert params["sandbox"] == "danger-full-access" and "permissions" not in params
    assert "dynamicTools" not in params
    assert phases[-1] == "model_response"


@pytest.mark.parametrize("denied", [False, True])
def test_claude_git_uses_native_tools_and_reports_denials(monkeypatch, tmp_path, denied):
    monkeypatch.setattr(coding_agents.claude_code_brain, "executable", lambda: "claude")

    def invoke(command, workspace, prompt, check, *, timeout, raw_stdin, env, label, on_line):
        assert workspace == tmp_path and raw_stdin
        assert "--json-schema" not in command and "--tools" not in command
        assert command[command.index("--permission-mode") + 1] == "bypassPermissions"
        on_line(json.dumps({"type": "result", "subtype": "success", "result": "作業報告",
                            "permission_denials": [{"tool_name": "Write"}] if denied else []}))
        return 0, "", ""

    monkeypatch.setattr(coding_agents.antigravity_cli_brain, "invoke", invoke)
    args = ("claude_code", {}, "合成開発", tmp_path, lambda: None, lambda _: None)
    if denied:
        with pytest.raises(coding_agents.antigravity_cli_brain.CLIError) as exc:
            coding_agents.run_git(*args)
        assert exc.value.reason == "permission_denied"
    else:
        assert coding_agents.run_git(*args) == "作業報告"
