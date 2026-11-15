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


def test_claude_git_resumes_session_and_reports_new_id(monkeypatch, tmp_path):
    monkeypatch.setattr(coding_agents.claude_code_brain, "executable", lambda: "claude")
    commands = []

    def invoke(command, workspace, prompt, check, *, timeout, raw_stdin, env, label, on_line):
        commands.append(command)
        if "--resume" in command and command[command.index("--resume") + 1] == "gone":
            # Shape observed from the official CLI for an unknown session ID.
            on_line(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True,
                                "num_turns": 0, "session_id": "gone"}))
            return 1, "", "No conversation found with session ID: gone"
        on_line(json.dumps({"type": "system", "subtype": "init", "session_id": "s-2"}))
        on_line(json.dumps({"type": "result", "subtype": "success", "result": "続きの報告", "session_id": "s-2"}))
        return 0, "", ""

    monkeypatch.setattr(coding_agents.antigravity_cli_brain, "invoke", invoke)
    seen = []
    args = ("claude_code", {}, "続き", tmp_path, lambda: None, lambda _: None)
    assert coding_agents.run_git(*args, resume="s-1", on_session=seen.append) == "続きの報告"
    assert commands[0][commands[0].index("--resume") + 1] == "s-1" and "--no-session-persistence" not in commands[0]
    assert seen == ["s-2"]
    with pytest.raises(coding_agents.antigravity_cli_brain.CLIError) as exc:
        coding_agents.run_git(*args, resume="gone", on_session=seen.append)
    assert exc.value.reason == "resume_unavailable" and seen == ["s-2"]


def test_antigravity_git_resumes_only_the_same_conversation(monkeypatch, tmp_path):
    conversation = "83d75605-0804-4d10-8787-fef77fe44190"
    other = "11111111-2222-4333-8444-555555555555"
    monkeypatch.setattr(coding_agents.antigravity_cli, "executable", lambda: "agy")
    reported = {"id": conversation}

    def invoke(command, workspace, prompt, check, *, timeout, on_line):
        assert command[command.index("--conversation") + 1] == conversation
        on_line(json.dumps({"event": "init", "conversation_id": reported["id"], "init": {}}))
        on_line(json.dumps({"event": "result", "result": {
            "conversation_id": reported["id"], "status": "SUCCESS", "response": "続きの報告"}}))
        return 0, "", ""

    monkeypatch.setattr(coding_agents.antigravity_cli_brain, "invoke", invoke)
    seen = []
    args = ("antigravity_cli", {}, "続き", tmp_path, lambda: None, lambda _: None)
    assert coding_agents.run_git(*args, resume=conversation, on_session=seen.append) == "続きの報告"
    assert seen == [conversation]
    reported["id"] = other
    with pytest.raises(coding_agents.antigravity_cli_brain.CLIError) as exc:
        coding_agents.run_git(*args, resume=conversation)
    assert exc.value.reason == "resume_unavailable"
    with pytest.raises(ValueError):
        coding_agents.run_git(*args, resume="--not-an-id")


def test_codex_git_persists_and_resumes_thread(monkeypatch, tmp_path):
    class DevelopmentRPC(FakeRPC):
        def __init__(self, *, workspace, development):
            super().__init__(workspace=workspace)

        def request(self, method, params=None, **kwargs):
            if method == "thread/resume" and params["threadId"] == "gone":
                self.requests.append((method, params))
                raise codex_brain.ResumeUnavailable("synthetic")
            return super().request(method, params, **kwargs)

    monkeypatch.setattr(codex_brain, "RPC", DevelopmentRPC)
    FakeRPC.clients = []
    FakeRPC.scripts = [[delta("初回"), complete()], [delta("続き"), complete()], []]
    seen = []
    args = ("codex", {}, "目的", tmp_path, lambda: None, lambda _: None)
    assert coding_agents.run_git(*args, on_session=seen.append) == "初回"
    start = next(params for method, params in FakeRPC.clients[0].requests if method == "thread/start")
    assert start["ephemeral"] is False
    assert coding_agents.run_git(*args, resume="synthetic-cli-thread", on_session=seen.append) == "続き"
    methods = [method for method, _ in FakeRPC.clients[1].requests]
    assert "thread/resume" in methods and "thread/start" not in methods
    assert seen == ["synthetic-cli-thread", "synthetic-cli-thread"]
    with pytest.raises(coding_agents.antigravity_cli_brain.CLIError) as exc:
        coding_agents.run_git(*args, resume="gone")
    assert exc.value.reason == "resume_unavailable" and FakeRPC.clients[2].closed


def test_structured_run_publishes_stream_activity_and_progress_details(monkeypatch):
    from backend import coding_stream
    turns = iter([
        ({"role": "assistant", "content": "Serverを確認します", "tool_calls": [
            {"id": "1", "type": "function", "function": {"name": "list_pc_dir", "arguments": '{"path": "C:\\\\#Project"}'}}
        ]}, {}),
        ({"role": "assistant", "content": "フォルダ一覧です", "tool_calls": []}, {}),
    ])
    monkeypatch.setattr(coding_agents.antigravity_cli_brain, "completion", lambda *a, **kw: next(turns))
    recorded = []
    job_id = "stream-test-job"
    try:
        with coding_stream.bind(job_id):
            reply = coding_agents.run(
                "antigravity_cli", {"model": "gemini-test"}, "一覧教えて",
                lambda name, args: {"path": args["path"], "directories": ["Server"], "files": []},
                lambda: None, lambda kind, detail="": recorded.append((kind, detail)),
                catalog=coding_agents.PC_CATALOG, instructions=coding_agents.PC_INSTRUCTIONS,
            )
            snap = coding_stream.snapshot(job_id)
    finally:
        coding_stream.clear(job_id)
    assert reply == "フォルダ一覧です"
    assert ("model_response", "Serverを確認します") in recorded
    assert ("tool_result", "list_pc_dir: フォルダ 1件 / ファイル 0件") in recorded
    assert "Serverを確認します" in snap["draft"] and "フォルダ一覧です" in snap["draft"]
    assert any("list_pc_dir" in item for item in snap["activity"])
