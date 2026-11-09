"""H5: Home file Tools give every Brain the same L0/L1 line, enforced by Core (#404)."""
import json
import subprocess
import pytest
from tests.test_setup_integrations import isolated  # noqa: F401 - autouse isolation
from tests.test_agent_workspace import fake  # noqa: F401 - fake Codex app-server fixture
from backend import brain, codex_brain, conversation_api as api, petit_home, setup_store, tools


def call(name, **arguments):
    raw = tools.dispatch(name, arguments)
    return raw if isinstance(raw, dict) else json.loads(raw)


def test_home_tools_are_public_with_expected_risk():
    names = {s["function"]["name"] for s in brain.schemas()}
    for name in ("list_home_files", "read_home_file", "search_home_files", "write_home_file", "edit_home_file"):
        assert name in names
    assert tools.risk_for("read_home_file") == "safe_read" and tools.risk_for("write_home_file") == "low_risk_write"
    assert not tools.requires_confirmation("write_home_file")


def test_l0_write_read_edit_search_list_and_history():
    assert call("write_home_file", path="memory/2026-11-09.md", content="会議: 10時\n")["written"] is True
    assert call("write_home_file", path="memory/2026-11-09.md", content="昼: 定食\n", mode="append")["written"]
    read = call("read_home_file", path="memory/2026-11-09.md")
    assert read["content"] == "会議: 10時\n昼: 定食" and read["total_lines"] == 2
    assert call("edit_home_file", path="memory/2026-11-09.md", old_text="定食", new_text="カレー")["edited"]
    assert call("search_home_files", query="カレー")["matches"][0]["path"] == "memory/2026-11-09.md"
    assert "memory/2026-11-09.md" in call("list_home_files", path="memory")["files"]
    log = subprocess.run(["git", "log", "--oneline"], cwd=petit_home.root(), capture_output=True, text=True).stdout
    assert "PETIT: memory/2026-11-09.md" in log


@pytest.mark.parametrize("path", ["../escape.md", "/etc/passwd", "~/.ssh/id_rsa", "scratch/.env", ".git/config"])
def test_outside_secrets_and_git_are_refused(path):
    assert call("read_home_file", path=path)["ok"] is False
    assert call("write_home_file", path=path, content="x")["ok"] is False


@pytest.mark.parametrize("name", ["AGENTS.md", "SOUL.md", "USER.md", "CLAUDE.md"])
def test_persona_is_readable_but_changes_need_diff_approval(name):
    assert call("read_home_file", path=name).get("content") is not None
    refused = call("write_home_file", path=name, content="x")
    assert refused["ok"] is False and "update_persona_file" in refused["error"]
    assert call("edit_home_file", path=name, old_text="#", new_text="x")["ok"] is False


def test_listing_hides_secrets_and_git():
    call("write_home_file", path="scratch/a.py", content="print(1)\n")
    (petit_home.root() / "scratch" / ".env").write_text("TOKEN=x")
    files = call("list_home_files")["files"]
    assert "scratch/a.py" in files and "scratch/.env" not in files and not any(f.startswith(".git/") for f in files)
    (petit_home.root() / "scratch" / "notes.txt").write_text("TOKEN here")
    assert all(m["path"] != "scratch/.env" for m in call("search_home_files", query="TOKEN")["matches"])


def test_ambiguous_edit_is_refused():
    call("write_home_file", path="scratch/x.txt", content="a a")
    assert "2 件" in call("edit_home_file", path="scratch/x.txt", old_text="a", new_text="b")["error"]


def test_worktree_files_are_l1_editable_but_not_their_git(tmp_path):
    wt = petit_home.ensure() / "worktrees" / "app-1"
    wt.mkdir(parents=True)
    (wt / ".git").write_text("gitdir: elsewhere")
    assert call("write_home_file", path="worktrees/app-1/main.py", content="print('hi')\n")["written"]
    assert call("write_home_file", path="worktrees/app-1/.git", content="x")["ok"] is False
    log = subprocess.run(["git", "log", "--oneline"], cwd=petit_home.root(), capture_output=True, text=True).stdout
    assert "worktrees/app-1/main.py" not in log  # worktrees are committed with commit_worktree, not Home history


def test_codex_agent_mode_works_in_home(fake):
    setup_store.update({"codex_agent_mode": True})
    api.submit("codex-home", "r-home", "こんにちは", is_admin=True)
    start = next(params for method, params in fake.calls if method == "thread/start")
    assert start["cwd"] == str(petit_home.root().resolve()) or start["cwd"] == str(petit_home.root())
    assert "write_home_file" in start["developerInstructions"] and "open_worktree" in start["developerInstructions"]
    assert start["sandbox"] == "read-only" and start["approvalPolicy"] == "never"


def test_codex_agent_mode_off_keeps_managed_workspace(fake):
    api.submit("codex-plain", "r-plain", "こんにちは", is_admin=True)
    start = next(params for method, params in fake.calls if method == "thread/start")
    assert start["cwd"].endswith("agent-workspace") and codex_brain.HOME_RULES not in start["developerInstructions"]


def test_codex_agent_mode_needs_admin(monkeypatch):
    setup_store.update({"codex_agent_mode": True})
    from backend import request_context
    with request_context.bind(request_id="x", session_id="y", is_admin=False):
        assert codex_brain.agent_mode() is False
