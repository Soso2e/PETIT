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
    result=coding_agents.run("codex",{"model":""},"合成開発",invoke,lambda:None,lambda kind:None)
    assert result == "変更内容と未確認事項" and FakeRPC.clients[0].closed
    invoke.assert_called_once_with("list_files",{})
    params=next(p for method,p in FakeRPC.clients[0].requests if method=="thread/start")
    assert params["dynamicTools"][0]["name"] == "petit_coding_tool"


def test_codex_coding_cancel_closes_client(monkeypatch):
    FakeRPC.clients=[];FakeRPC.scripts=[[]]
    monkeypatch.setattr(codex_brain,"RPC",FakeRPC)
    def check():raise InterruptedError("cancel")
    with pytest.raises(InterruptedError):
        coding_agents.run("codex",{"model":""},"合成開発",Mock(),check,lambda kind:None)
    assert FakeRPC.clients[0].closed


def test_antigravity_coding_uses_scoped_catalog_and_saved_results(monkeypatch):
    responses=iter([({"role":"assistant","content":"","tool_calls":[{"id":"call","type":"function","function":{"name":"list_files","arguments":"{}"}}]},{}),
                    ({"role":"assistant","content":"完了候補です。実テスト未実施。","tool_calls":[]},{})])
    captured=[]
    def completion(target,messages,catalog,check):
        captured.append(list(messages))
        assert {x["function"]["name"] for x in catalog} == {"list_files","read_file","write_file","run_static_checks"}
        return next(responses)
    monkeypatch.setattr(coding_agents.antigravity_cli_brain,"completion",completion)
    result=coding_agents.run("antigravity_cli",{},"合成開発",lambda *a:{"files":["answer.py"]},lambda:None,lambda kind:None)
    assert "実テスト未実施" in result and captured[1][-1]["role"] == "tool"
