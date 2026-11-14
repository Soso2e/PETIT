"""Protocol lifecycle checks; synthetic RPC only, no actual Codex inference."""
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
