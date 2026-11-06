"""Claude Code CLI Executor contracts. Synthetic CLI output only; no real account or inference."""
import json
from unittest.mock import Mock

import pytest

from backend import antigravity_cli_brain as shared, brain, brain_priority, claude_code_brain as runtime, coding_agents, db
from backend import setup_store as settings, conversation_api as conversations, conversation_store as store
from tests.test_setup_integrations import isolated, client, admin


def output(content="合成Claude応答", calls=None, **extra):
    value = {"type": "result", "subtype": "success", "is_error": False, "result": "",
             "structured_output": {"content": content, "tool_calls": calls or []},
             "usage": {"input_tokens": 3, "output_tokens": 4, "private": "x"}, "total_cost_usd": 0.01,
             "permission_denials": [], **extra}
    return 0, json.dumps(value, ensure_ascii=False), ""


@pytest.fixture
def selected(monkeypatch):
    monkeypatch.setattr(runtime, "executable", lambda: "synthetic-claude")
    settings.update({"brain_enabled": True, "brain_transport": "cli_only", "claude_code_enabled": True,
                     "connected": ["claude_code"], "priority": ["antigravity_cli", "codex", "claude_code", "deepseek"]})


def test_chat_turn_uses_locked_down_command_and_replays(selected, monkeypatch):
    invoke = Mock(return_value=output())
    monkeypatch.setattr(shared, "invoke", invoke)
    result = conversations.submit("thread", "hello", "合成入力")
    assert result["status"] == "completed" and result["reply"] == "合成Claude応答"
    assert result["model_route"]["provider"] == "claude_code" and result["model_route"]["transport"] == "cli"
    assert conversations.submit("thread", "hello", "合成入力")["reply"] == result["reply"]
    assert invoke.call_count == 1
    command = invoke.call_args.args[0]
    assert command[:4] == ["synthetic-claude", "-p", "--output-format", "json"]
    assert command[command.index("--tools") + 1] == "" and "--strict-mcp-config" in command
    assert command[command.index("--setting-sources") + 1] == "" and "--no-session-persistence" in command
    assert "--dangerously-skip-permissions" not in command and "合成入力" not in " ".join(command)
    assert invoke.call_args.kwargs["raw_stdin"] is True and "合成入力" in invoke.call_args.args[2]
    with db.get_connection() as connection:
        payload = json.loads(connection.execute("SELECT payload_json FROM turn_events WHERE type='claude_code_step'").fetchone()[0])
    assert payload["usage"] == {"input_tokens": 3, "output_tokens": 4} and payload["quota_remaining"] == "unknown"


def test_read_then_approved_write_goes_through_core(selected, monkeypatch):
    invoke = Mock(side_effect=[output(calls=[{"name": "get_current_time", "arguments": {}}]),
        output(calls=[{"name": "add_schedule", "arguments": {"title": "Claude予定", "start_time": "2026-11-07T21:00:00+09:00"}}]),
        output("保存結果を確認しました")])
    monkeypatch.setattr(shared, "invoke", invoke)
    result = conversations.submit("thread", "write", "合成予定を追加", is_admin=True)
    assert result["status"] == "waiting_approval"
    with db.get_connection() as connection:
        assert connection.execute("SELECT count(*) FROM calendar_events_cache").fetchone()[0] == 0
    done = conversations.decide(store.approvals("write")[0]["approval_id"], True)
    assert done["status"] == "completed" and invoke.call_count == 3
    with db.get_connection() as connection:
        assert connection.execute("SELECT count(*) FROM effect_receipts").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM calendar_events_cache").fetchone()[0] == 1


@pytest.mark.parametrize("raw", [
    "not json", "[]", json.dumps({"type": "assistant"}),
    json.dumps({"type": "result", "subtype": "success", "is_error": False,
                "structured_output": {"content": "", "tool_calls": [{"name": "Bash", "arguments": {}}]}}),
    json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "{}"}),
    json.dumps({"type": "result", "subtype": "success", "is_error": False, "permission_denials": [{"tool_name": "Bash"}],
                "structured_output": {"content": "x", "tool_calls": []}})])
def test_invalid_or_direct_tool_output_never_executes(raw):
    with pytest.raises(shared.CLIError):
        runtime.parse_output(raw, brain.schemas())


@pytest.mark.parametrize("text,reason", [("Not logged in · Please run /login", "authentication_required"),
                                         ("Claude AI usage limit reached", "usage_limit"),
                                         ("Credit balance is too low", "usage_limit")])
def test_error_results_map_to_safe_reasons(text, reason):
    raw = json.dumps({"type": "result", "subtype": "success", "is_error": True, "result": text})
    with pytest.raises(shared.CLIError) as caught:
        runtime.parse_output(raw, [])
    assert caught.value.reason == reason and text not in str(caught.value)


def test_api_keys_and_core_secrets_are_not_forwarded(monkeypatch):
    for key in ["ANTHROPIC_API_KEY", "PETIT_BOOTSTRAP_TOKEN", "DEEPSEEK_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"]:
        monkeypatch.setenv(key, "SYNTHETIC-SECRET")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/synthetic/config")
    env = runtime.environment()
    assert "SYNTHETIC-SECRET" not in json.dumps(env) and env["CLAUDE_CONFIG_DIR"] == "/synthetic/config"


def test_not_permitted_without_explicit_connection(monkeypatch):
    monkeypatch.setattr(runtime, "executable", lambda: "synthetic-claude")
    data = {**settings.load(), "connected": ["claude_code"], "claude_code_enabled": False}
    assert not brain_priority.permitted("claude_code", data)
    assert brain_priority.permitted("claude_code", {**data, "claude_code_enabled": True, "brain_transport": "cli_only"})


def test_policy_insert_keeps_user_order():
    assert brain_priority.insert_by_policy(["codex", "deepseek"], "claude_code") == ["codex", "claude_code", "deepseek"]
    assert brain_priority.insert_by_policy(["deepseek", "codex"], "claude_code") == ["claude_code", "deepseek", "codex"]
    assert brain_priority.insert_by_policy(["codex"], "claude_code") == ["codex", "claude_code"]
    assert settings.DEFAULTS["priority"] == brain_priority.POLICY_ORDER


def test_connect_disconnect_and_models(client, monkeypatch):
    admin(client)
    monkeypatch.setattr(runtime, "executable", lambda: "synthetic-claude")
    settings.update({"priority": ["codex", "deepseek"]})
    assert client.post("/api/setup/services/claude_code/connect").status_code == 200
    assert settings.load()["priority"] == ["codex", "claude_code", "deepseek"]
    runtime.require_production_permission()
    assert client.get("/api/setup/claude-code").json()["production_enabled"]
    assert client.get("/api/setup/config").json()["claude_code"]["installed"]
    models = client.post("/api/setup/services/claude_code/models").json()["models"]
    assert {x["id"] for x in models} == {"sonnet", "opus", "haiku"}
    assert client.put("/api/setup/config", json={"claude_code_model": "opus; rm"}).status_code == 422
    assert client.put("/api/setup/config", json={"claude_code_model": "claude-sonnet-5-5"}).status_code == 200
    assert client.post("/api/setup/services/claude_code/disconnect").status_code == 200
    with pytest.raises(ValueError):
        runtime.require_production_permission()


def test_coding_job_runs_through_core_catalog(selected, monkeypatch):
    steps = [({"role": "assistant", "content": "", "tool_calls": [{"id": "cc-1", "type": "function",
              "function": {"name": "list_files", "arguments": "{}"}}]}, {}),
             ({"role": "assistant", "content": "静的チェックのみ実施", "tool_calls": []}, {})]
    completion = Mock(side_effect=steps)
    monkeypatch.setattr(runtime, "completion", completion)
    invoke = Mock(return_value={"files": ["README.md"]})
    reply = coding_agents.run("claude_code", brain_priority.target("claude_code"), "目的", invoke, lambda: None, lambda _: None)
    assert reply == "静的チェックのみ実施" and invoke.call_args.args == ("list_files", {})
    assert completion.call_args.args[2] is coding_agents.CATALOG


def test_discover_tools_is_accepted_from_cli_catalog(selected, monkeypatch):
    # Regression: the prompt advertises discover_tools, so the validator must accept it.
    invoke = Mock(side_effect=[output(calls=[{"name": "discover_tools", "arguments": {"names": ["add_schedule"]}}]),
                               output("確認しました")])
    monkeypatch.setattr(shared, "invoke", invoke)
    result = conversations.submit("thread", "discover", "予定を入れる準備", is_admin=True)
    assert result["status"] == "completed" and invoke.call_count == 2
    assert '"add_schedule"' in invoke.call_args.args[2]
