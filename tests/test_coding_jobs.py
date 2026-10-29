"""Local fixture repositories/DB only; mock agents are not live CLI acceptance."""
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend import coding_jobs as jobs, coding_api, coding_agents, config, db, setup_store as settings
from backend import setup_api, brain, tools, conversation_store as store, conversation_api as conversations
from tests.test_setup_integrations import isolated, admin


@pytest.fixture
def repository(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STORAGE_DIR", tmp_path / "storage")
    config.STORAGE_DIR.mkdir()
    root = tmp_path / "repository";root.mkdir()
    jobs.git(root, "init", "-q")
    (root / "AGENTS.md").write_text("Keep edits small. Do not delete files.\n", encoding="utf-8")
    (root / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    jobs.git(root, "add", "--", "AGENTS.md", "main.py")
    jobs.git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture")
    settings.update({"coding_roots": [str(root)], "connected": ["codex", "antigravity_cli"], "antigravity_cli_enabled": True})
    monkeypatch.setattr("backend.antigravity_cli.executable", lambda: "synthetic-agy")
    monkeypatch.setattr("backend.brain_priority.shutil.which", lambda _: "synthetic-codex")
    jobs._stop.clear()
    jobs.ensure_schema()
    return root


def synthetic_agent(provider, target, goal, invoke, check, progress):
    assert "main.py" in invoke("list_files", {})["files"]
    invoke("read_file", {"path": "AGENTS.md"})
    previous = invoke("read_file", {"path": "main.py"})
    assert previous["content"].replace("\r\n", "\n") == "VALUE = 1\n"
    assert invoke("write_file", {"path": "main.py", "content": "VALUE = 2\n", "expected_sha256": previous["sha256"]})["saved"]
    assert invoke("run_static_checks", {})["ok"]
    return "合成Agentで変更しました。実テストは未実施です。"


@pytest.fixture
def client():
    app = FastAPI();app.include_router(setup_api.router);app.include_router(coding_api.router);setup_api.install(app)
    return TestClient(app, base_url="http://localhost", client=("127.0.0.1", 12345), headers={"X-PETIT-Request": "1"})


@pytest.mark.parametrize("provider", ["codex", "antigravity_cli"])
def test_approval_once_isolated_copy_and_source_dirty_preserved(repository, monkeypatch, provider):
    agent = Mock(side_effect=synthetic_agent);monkeypatch.setattr(coding_agents, "run", agent)
    head = jobs.git(repository, "rev-parse", "HEAD").strip()
    (repository / "main.py").write_text("USER_DIRTY = True\n", encoding="utf-8")
    proposed = jobs.create("request", str(repository), "変更してください", provider, base_commit=head)
    assert not proposed["started"] and not jobs.pump()
    job_id = proposed["job_id"]
    jobs.approve(job_id);jobs.approve(job_id)
    assert jobs.pump() and not jobs.pump()
    result = jobs.get(job_id)
    assert result["status"] == "ready_for_review" and result["checks"]["ok"]
    assert result["tests"] == "not_run" and result["host_acceptance"] == "not_verified"
    assert result["branch"].startswith("fix/petit-") and agent.call_count == 1
    assert (repository / "main.py").read_text() == "USER_DIRTY = True\n"
    assert (Path(result["workspace"]) / "main.py").read_text() == "VALUE = 2\n"
    assert not jobs.git(result["workspace"], "remote").strip()
    assert jobs.create("request", str(repository), "変更してください", provider, base_commit=head)["job_id"] == job_id
    with db.get_connection() as connection:
        assert connection.execute("SELECT status FROM tasks_cache WHERE id=?", (result["task_id"],)).fetchone()[0] != "done"


def test_input_hash_conflict_and_allowlist_revalidation(repository, monkeypatch):
    job_id = jobs.create("one", str(repository), "目的", "codex", approved=True)["job_id"]
    with pytest.raises(ValueError):jobs.create("one", str(repository), "別目的", "codex")
    settings.update({"coding_roots": []})
    agent=Mock();monkeypatch.setattr(coding_agents, "run", agent)
    assert jobs.pump() and jobs.get(job_id)["status"] == "failed"
    agent.assert_not_called()


def test_changed_base_commit_is_rejected_before_approval(repository):
    job_id = jobs.create("one", str(repository), "目的", "codex")["job_id"]
    jobs.git(repository, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--allow-empty", "-qm", "new")
    with pytest.raises(ValueError, match="開始コミット"):jobs.approve(job_id)
    assert jobs.get(job_id)["status"] == "proposed"


def test_cancellation_before_run_preserves_source(repository, monkeypatch):
    job_id = jobs.create("one", str(repository), "目的", "codex", approved=True)["job_id"]
    jobs.cancel(job_id)
    agent=Mock();monkeypatch.setattr(coding_agents,"run",agent)
    assert not jobs.pump() and jobs.get(job_id)["status"] == "cancelled"
    agent.assert_not_called()


def test_cancellation_during_agent_keeps_edits(repository, monkeypatch):
    job_id = jobs.create("one", str(repository), "目的", "codex", approved=True)["job_id"]
    def runtime(*args):
        summary=synthetic_agent(*args)
        jobs.cancel(job_id)
        args[4]()
        return summary
    monkeypatch.setattr(coding_agents,"run",runtime)
    jobs.pump();result=jobs.get(job_id)
    assert result["status"] == "cancelled" and Path(result["workspace"],"main.py").exists()


@pytest.mark.parametrize("name", ["../outside.py", ".git/config", "_private/note.md", ".env", ".env.production", "C:/outside.py", "file:stream"])
def test_protected_paths_cannot_be_read_or_written(repository, name):
    with pytest.raises(ValueError):jobs.path_for(repository, name)


def test_toolbox_stale_hash_and_unread_instructions(repository):
    invoke=jobs.toolbox({"id":"synthetic", "workspace":str(repository)}, lambda:None)
    assert invoke("write_file",{"path":"main.py","content":"VALUE = 3\n","expected_sha256":"wrong"})["error"] == "read_applicable_AGENTS_first"
    invoke("read_file",{"path":"AGENTS.md"})
    assert invoke("write_file",{"path":"main.py","content":"VALUE = 3\n","expected_sha256":"wrong"})["error"] == "file_changed_read_again"
    assert invoke("run_command",{"command":"anything"})["error"] == "invalid_tool_arguments"
    assert (repository/"main.py").read_text() == "VALUE = 1\n"


def test_restart_marks_running_interrupted_without_replay(repository):
    job_id=jobs.create("one",str(repository),"目的","codex",approved=True)["job_id"]
    with db.get_connection() as connection:connection.execute("UPDATE coding_jobs SET status='running' WHERE id=?",(job_id,))
    try:jobs.start();assert jobs.get(job_id)["status"] == "interrupted"
    finally:jobs.stop()


def test_api_auth_proposal_diff_and_manual_completion(repository, client, monkeypatch):
    assert client.get("/api/coding/jobs").status_code == 401
    admin(client)
    assert client.put("/api/coding/config",json={"paths":[str(repository)]},headers={"Origin":"https://evil.example"}).status_code == 403
    monkeypatch.setattr(coding_agents,"run",synthetic_agent)
    payload={"request_id":"web-one","repository":str(repository),"provider":"codex","goal":"合成変更"}
    job_id=client.post("/api/coding/jobs",json=payload).json()["job_id"]
    assert client.post(f"/api/coding/jobs/{job_id}/complete").status_code == 409
    assert client.post(f"/api/coding/jobs/{job_id}/approve").status_code == 200
    jobs.pump()
    diff=client.get(f"/api/coding/jobs/{job_id}/diff").json()
    assert diff["files"] == ["main.py"] and "+VALUE = 2" in diff["diff"]
    completed=client.post(f"/api/coding/jobs/{job_id}/complete").json()
    assert completed["status"] == "completed" and completed["tests"] == "not_run"
    with db.get_connection() as connection:
        assert connection.execute("SELECT status FROM tasks_cache WHERE id=?",(completed["task_id"],)).fetchone()[0] == "done"


def test_chat_delegation_uses_existing_approval_and_receipt(repository, monkeypatch):
    head=jobs.git(repository,"rev-parse","HEAD").strip()
    arguments={"repository":str(repository),"goal":"合成開発依頼","provider":"codex","base_commit":head}
    responses=iter([{"role":"assistant","content":"","tool_calls":[{"id":"delegate","type":"function","function":{
        "name":"delegate_coding_task","arguments":json.dumps(arguments)}}]}, {"role":"assistant","content":"キューへ登録しました。"}])
    monkeypatch.setattr(brain.lmstudio_client,"chat_completion",lambda *a,**k:next(responses))
    monkeypatch.setattr(brain,"check_provider",lambda thread:{"provider":"lm_studio","profile":"local","model":"synthetic","base_url":"http://localhost","configured":True})
    result=conversations.submit("coding-chat","coding-request","開発をお願い", is_admin=True)
    assert result["status"] == "waiting_approval" and not jobs.list_jobs()
    approval=store.approvals("coding-request")[0]["approval_id"]
    assert conversations.decide(approval,True)["status"] == "completed"
    assert conversations.decide(approval,True)["status"] == "completed"
    assert len(jobs.list_jobs()) == 1 and jobs.list_jobs()[0]["status"] == "queued"
    with db.get_connection() as connection:
        assert connection.execute("SELECT count(*) FROM effect_receipts WHERE tool='delegate_coding_task'").fetchone()[0] == 1


def test_local_only_thread_cannot_delegate_private_context(repository):
    from backend import request_context
    from backend.tools.coding import delegate_coding_task
    store.create_thread("private-coding",privacy="local_only")
    with request_context.bind(request_id="private-request",session_id="private-coding"):
        with pytest.raises(ValueError,match="ローカル専用"):
            delegate_coding_task(str(repository),"private-goal","codex",jobs.git(repository,"rev-parse","HEAD").strip())
    assert not jobs.list_jobs()
