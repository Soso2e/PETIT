"""H4: worktrees in PETIT Home — L1 edit/test/commit/push petit/ branches, L2 PR approval (#401)."""
import json
import os
import subprocess
import sys
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.test_setup_integrations import isolated  # noqa: F401 - autouse isolation
from backend import (agent_bridge, agent_hooks as hooks, conversation_store as store, db, petit_home, setup_store,
                     tools, worktrees)


def sh(*args, cwd):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    origin = tmp_path / "origin.git"
    sh("git", "init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    work = tmp_path / "myapp"
    sh("git", "clone", "-q", str(origin), str(work), cwd=tmp_path)
    (work / "app.py").write_text("def add(a, b):\n    return a + b\n")
    (work / "test_app.py").write_text("from app import add\n\ndef test_add():\n    assert add(1, 2) == 3\n")
    for args in (("add", "-A"), ("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"), ("push", "-q", "origin", "main")):
        sh("git", *args, cwd=work)
    sh("git", "remote", "set-head", "origin", "main", cwd=work)
    setup_store.update({"coding_roots": [str(work)]})
    return work, origin


def test_open_worktree_lives_in_home_on_a_petit_branch(repo):
    work, _ = repo
    opened = worktrees.open_worktree(str(work), "Fix add overflow")
    path = petit_home.root() / opened["path"]
    assert opened["path"].startswith("worktrees/myapp-") and path.is_dir()
    assert opened["branch"].startswith("petit/fix-add-overflow-") and opened["base"] == "main"
    assert sh("git", "rev-parse", "--abbrev-ref", "HEAD", cwd=path) == opened["branch"]
    assert "worktrees" not in sh("git", "status", "--porcelain", cwd=petit_home.root())  # Home git ignores it


def test_unregistered_repository_is_refused(tmp_path, repo):
    other = tmp_path / "other"
    other.mkdir()
    sh("git", "init", "-q", str(other), cwd=tmp_path)
    with pytest.raises(ValueError):
        worktrees.open_worktree(str(other), "x")


@pytest.mark.parametrize("argv", [["python", "-m", "pytest", "-q"], ["npm", "test"], ["npm", "run", "lint"],
                                  ["npx", "eslint", "."], ["go", "test", "./..."], ["cargo", "test"], ["pytest"], ["make", "test"]])
def test_check_commands_allowed(argv):
    assert worktrees.validate_check_command(argv) == argv


@pytest.mark.parametrize("argv", [[], ["bash", "-c", "curl x"], ["python", "-c", "import os"], ["python", "evil.py"],
                                  ["npm", "install"], ["npm", "publish"], ["npx", "some-pkg"], ["go", "run", "."],
                                  ["/tmp/pytest"], ["git", "push"], ["rm", "-rf", "."]])
def test_check_commands_refused(argv):
    with pytest.raises(worktrees.WorktreeError):
        worktrees.validate_check_command(argv)


def test_edit_test_commit_push_flow(repo):
    work, origin = repo
    opened = worktrees.open_worktree(str(work), "subtract")
    wid, path = opened["worktree_id"], petit_home.root() / opened["path"]
    (path / "app.py").write_text("def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n")
    (path / "test_sub.py").write_text("from app import sub\n\ndef test_sub():\n    assert sub(3, 1) == 2\n")
    check = worktrees.run_check(wid, [Path(sys.executable).name if Path(sys.executable).name.startswith("python") else "python",
                                      "-m", "pytest", "-q", "-p", "no:cacheprovider"])
    assert check["passed"] is True and "2 passed" in check["output"], check["output"][-500:]
    status = worktrees.status(wid)
    assert "test_sub.py" in status["changes"]
    committed = worktrees.commit(wid, "feat: sub を追加")
    assert committed["committed"] is True
    with pytest.raises(worktrees.WorktreeError, match="一致しません"):
        worktrees.push(wid, "0000000")
    pushed = worktrees.push(wid, committed["commit"][:12])
    assert pushed["pushed"] is True
    assert sh("git", "rev-parse", opened["branch"], cwd=origin) == committed["commit"]
    assert sh("git", "rev-parse", "main", cwd=origin) != committed["commit"]  # main untouched


def test_failing_tests_are_reported_as_failing(repo):
    work, _ = repo
    opened = worktrees.open_worktree(str(work), "break")
    path = petit_home.root() / opened["path"]
    (path / "test_app.py").write_text("def test_fail():\n    assert 1 == 2\n")
    check = worktrees.run_check(opened["worktree_id"], ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"])
    assert check["passed"] is False and check["exit_code"] != 0


def test_push_never_targets_protected_or_foreign_branches(repo):
    work, _ = repo
    opened = worktrees.open_worktree(str(work), "x")
    wid, path = opened["worktree_id"], petit_home.root() / opened["path"]
    (path / "n.txt").write_text("n")
    head = worktrees.commit(wid, "n")["commit"]
    for branch in ("main", "petit/main", "feature/other"):
        with db.get_connection() as connection:
            connection.execute("UPDATE petit_worktrees SET branch=? WHERE id=?", (branch, wid))
        with pytest.raises(worktrees.WorktreeError):
            worktrees.push(wid, head)
    with db.get_connection() as connection:
        connection.execute("UPDATE petit_worktrees SET branch=? WHERE id=?", (opened["branch"], wid))
    sh("git", "checkout", "-q", "-b", "petit/sneaky", cwd=path)
    with pytest.raises(worktrees.WorktreeError, match="ブランチが作成時と違います"):
        worktrees.push(wid, head)


def test_pull_request_needs_push_and_records_url(repo, tmp_path, monkeypatch):
    work, _ = repo
    opened = worktrees.open_worktree(str(work), "pr")
    wid, path = opened["worktree_id"], petit_home.root() / opened["path"]
    (path / "n.txt").write_text("n")
    head = worktrees.commit(wid, "add n")["commit"]
    with pytest.raises(worktrees.WorktreeError, match="push"):
        worktrees.create_pull_request(wid, "t", "b")
    worktrees.push(wid, head)
    preview = tools.preview_for("create_worktree_pull_request", {"worktree_id": wid, "title": "T", "body": "B"})
    assert "add n" in preview and "→ main" in preview and "push 済み" in preview
    fake = tmp_path / "bin"
    fake.mkdir()
    monkeypatch.setattr(worktrees.shutil, "which", lambda name, path=None: str(fake / "gh") if name == "gh" else None)
    run = worktrees.subprocess.run

    def run_with_gh(argv, **kwargs):
        if argv[0] == str(fake / "gh"):
            return subprocess.CompletedProcess(argv, 0, b"https://github.com/example/myapp/pull/7\n", b"")
        return run(argv, **kwargs)

    monkeypatch.setattr(worktrees.subprocess, "run", run_with_gh)
    created = worktrees.create_pull_request(wid, "T", "B")
    assert created["url"].endswith("/pull/7") and created["pr_url"].endswith("/pull/7")


def test_close_removes_folder_but_keeps_branch(repo):
    work, _ = repo
    opened = worktrees.open_worktree(str(work), "tmp")
    path = petit_home.root() / opened["path"]
    worktrees.close(opened["worktree_id"])
    assert not path.exists() and opened["branch"] in sh("git", "branch", "--list", opened["branch"], cwd=work)
    with pytest.raises(worktrees.WorktreeError):
        worktrees.status(opened["worktree_id"])


def test_hook_treats_worktree_as_l1_but_protects_git(repo):
    work, _ = repo
    opened = worktrees.open_worktree(str(work), "hook")
    home = petit_home.root()
    assert hooks.decide("Edit", {"file_path": opened["path"] + "/app.py"}, home) is None
    assert hooks.decide("Write", {"file_path": opened["path"] + "/.git"}, home) == hooks.L3_REASON
    assert hooks.decide("Bash", {"command": "git worktree add /tmp/x"}, home) == hooks.L2_REASON
    assert hooks.decide("Read", {"file_path": str(work / "app.py")}, home) == hooks.OUTSIDE_REASON


def test_mcp_catalog_routes_new_development_through_proposal(repo):
    work, _ = repo
    store.create_thread("t-wt")
    store.accept("t-wt", "r-wt", {"message": "m", "is_admin": True})
    store.claim("r-wt")
    app = FastAPI()
    app.include_router(agent_bridge.router)
    client = TestClient(app)
    headers = {"Authorization": "Bearer " + agent_bridge.issue("r-wt")}

    def call(name, arguments):
        return client.post("/api/agent-bridge/tools/call", json={"name": name, "arguments": arguments}, headers=headers).json()

    listed = client.post("/api/agent-bridge/tools/list", headers=headers).json()
    assert "propose_development_job" in {entry["name"] for entry in listed["tools"]}
    assert call("open_worktree", {"repository": str(work), "task": "mcp"})["isError"]
    assert call("push_worktree", {})["isError"]
    assert call("create_worktree_pull_request", {})["isError"]
    assert not store.approvals("r-wt")
