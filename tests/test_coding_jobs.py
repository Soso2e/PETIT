"""Local fixture repositories/DB only; mock agents are not live CLI acceptance."""
import hashlib
import json
from contextlib import closing
from pathlib import Path
import sqlite3
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend import coding_jobs as jobs, coding_api, coding_agents, config, db, development_models, setup_store as settings
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
    monkeypatch.setattr("backend.codex_brain.executable", lambda: "synthetic-codex")
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


def test_job_progress_stream_requires_admin_and_omits_job_details(repository, client):
    job_id = jobs.create("progress", str(repository), "private goal", "antigravity_cli")["job_id"]
    route = f"/api/coding/jobs/{job_id}/stream"
    assert client.get(route).status_code in {401, 403}
    admin(client)
    assert client.get("/api/coding/jobs/missing/stream").status_code == 404
    jobs.event(job_id, "cli_responding", "private output")
    response = client.get(route)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert '"phase": "cli_responding"' in response.text
    assert "private" not in response.text


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
    assert result["task_id"] is None
    with db.get_connection() as connection:
        assert connection.execute("SELECT count(*) FROM tasks_cache").fetchone()[0] == 0


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
    assert completed["task_id"] is None
    with db.get_connection() as connection:
        assert connection.execute("SELECT count(*) FROM tasks_cache").fetchone()[0] == 0


@pytest.fixture
def development_quota(monkeypatch):
    quota = {key: {"available": key == "codex_sol", "five_hour": 80, "weekly": 50} for key in development_models.MODELS}
    monkeypatch.setattr(development_models, "usage", lambda: quota)


def test_chat_development_proposal_uses_receipt_and_waits_for_owner(repository, development_quota, monkeypatch):
    arguments={"repository":str(repository),"goal":"合成開発依頼","model_key":"codex_sol"}
    responses=iter([{"role":"assistant","content":"","tool_calls":[{"id":"delegate","type":"function","function":{
        "name":"propose_development_job","arguments":json.dumps(arguments)}}]}, {"role":"assistant","content":"開始を確認してください。"}])
    monkeypatch.setattr(brain.lmstudio_client,"chat_completion",lambda *a,**k:next(responses))
    monkeypatch.setattr(brain,"check_provider",lambda thread:{"provider":"lm_studio","profile":"local","model":"synthetic","base_url":"http://localhost","configured":True})
    result=conversations.submit("coding-chat","coding-request","開発をお願い", is_admin=True)
    job_id = result["development_job_id"]
    assert result["status"] == "completed" and jobs.get(job_id)["status"] == "proposed"
    assert not jobs.pump()
    assert jobs.list_jobs("coding-chat")[0]["id"] == job_id
    assert db.recent_conversations(session_id="coding-chat")[0]["development_job_id"] == job_id
    assert jobs.approve(job_id)["status"] == jobs.approve(job_id)["status"] == "queued"
    with db.get_connection() as connection:
        assert connection.execute("SELECT count(*) FROM effect_receipts WHERE tool='propose_development_job'").fetchone()[0] == 1


def test_develop_direct_runs_checks_and_reviews_committed_changes(repository, client, development_quota, monkeypatch):
    admin(client)
    (repository / "test_main.py").write_text(
        "import unittest\nfrom main import VALUE\n\n"
        "class TestValue(unittest.TestCase):\n"
        "    def test_new_value(self):\n"
        "        self.assertEqual(VALUE, 2)\n", encoding="utf-8")
    jobs.git(repository, "add", "test_main.py")
    jobs.git(repository, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "add test")
    observed = {}

    def agent(provider, target, goal, invoke, check, progress, **kwargs):
        observed["target"] = (target["model"], target["effort"])
        synthetic_agent(provider, target, goal, invoke, check, progress)
        observed["check"] = invoke("run_repository_check", {"argv": ["python", "-m", "unittest", "discover"]})
        observed["commit"] = invoke("commit_repository", {"message": "Update fixture value"})
        observed["push"] = invoke("push_repository", {})
        return "fixture"

    monkeypatch.setattr(coding_agents, "run", agent)
    payload = {"request_id": "direct", "repository": str(repository), "goal": "合成変更", "effort": "high"}
    job = client.post("/api/coding/jobs/start", json=payload).json()
    assert job["status"] == "queued"
    assert client.post("/api/coding/jobs/start", json=payload).json()["id"] == job["id"]
    assert jobs.pump()
    detail = jobs.get(job["id"])
    assert observed["target"] == ("gpt-6.1-sol", "high")
    assert observed["check"].get("passed"), observed["check"]
    assert observed["commit"].get("committed"), observed["commit"]
    assert observed["push"]["error"] == "invalid_tool_arguments"
    assert detail["status"] == "ready_for_review" and detail["tests"] == "passed", detail["error"]
    result = client.get(f"/api/coding/jobs/{job['id']}/diff").json()
    assert result["files"] == ["main.py"] and "+VALUE = 2" in result["diff"]
    assert (repository / "main.py").read_text(encoding="utf-8") == "VALUE = 1\n"


def test_pc_scope_copy_and_approval_for_original(repository, client, development_quota, monkeypatch, tmp_path):
    admin(client)
    folder = tmp_path / "documents"
    folder.mkdir()
    original = folder / "note.txt"
    original.write_text("before", encoding="utf-8")
    secret = folder / ".env"
    secret.write_text("hidden", encoding="utf-8")
    added = client.post("/api/coding/config/root", json={"path": str(folder)})
    assert added.status_code == 200 and added.json()["repositories"][-1]["mode"] == "folder"

    def agent(provider, target, goal, invoke, check, progress, **kwargs):
        assert invoke("read_pc_file", {"path": str(original)})["content"] == "before"
        assert "error" in invoke("read_pc_file", {"path": str(secret)})
        assert "error" in invoke("read_pc_file", {"path": str(repository / "main.py")})
        assert invoke("copy_pc_file_to_workspace", {"path": str(original), "destination": "copy.txt"})["copied"]
        copy = invoke("read_file", {"path": "copy.txt"})
        assert invoke("write_file", {"path": "copy.txt", "content": "after", "expected_sha256": copy["sha256"]})["saved"]
        assert invoke("write_pc_file", {"path": str(original), "source": "copy.txt"})["approval_required"]
        assert original.read_text(encoding="utf-8") == "before"
        return "承認待ち"

    monkeypatch.setattr(coding_agents, "run", agent)
    job = client.post("/api/coding/jobs/start", json={"request_id": "pc", "repository": str(folder), "goal": "編集"}).json()
    jobs.pump()
    detail = jobs.get(job["id"])
    assert detail["status"] == "waiting_approval"
    action = detail["actions"][0]
    endpoint = f"/api/coding/jobs/{job['id']}/actions/{action['id']}"
    assert "-before" in client.get(endpoint + "/preview").json()["preview"]
    assert client.post(endpoint + "/approve").json()["status"] == "applied"
    assert client.post(endpoint + "/approve").json()["status"] == "applied"
    assert original.read_text(encoding="utf-8") == "after"
    assert jobs.get(job["id"])["status"] == "ready_for_review"
    assert client.request("DELETE", "/api/coding/config/root", json={"path": str(folder)}).status_code == 200


def test_local_only_thread_cannot_delegate_private_context(repository):
    from backend import request_context
    from backend.tools.coding import delegate_coding_task
    store.create_thread("private-coding",privacy="local_only")
    with request_context.bind(request_id="private-request",session_id="private-coding"):
        with pytest.raises(ValueError,match="ローカル専用"):
            delegate_coding_task(str(repository),"private-goal","codex",jobs.git(repository,"rev-parse","HEAD").strip())
    assert not jobs.list_jobs()


def test_job_creation_does_not_add_to_tasks_cache(repository, development_quota):
    # jobs.create should not insert into tasks_cache
    created = jobs.create("req-no-task", str(repository), "タスクを作らない開発依頼", "codex")
    assert created["task_id"] is None
    job = jobs.get(created["job_id"])
    assert job["task_id"] is None

    # jobs.create_development should not insert into tasks_cache
    dev_job = jobs.create_development("dev-req-no-task", str(repository), "開発ジョブでもタスクは作らない", "codex_sol")
    assert dev_job["task_id"] is None

    with db.get_connection() as connection:
        assert connection.execute("SELECT count(*) FROM tasks_cache").fetchone()[0] == 0


def test_job_explicit_task_id_links_and_completes(repository, client, monkeypatch):
    monkeypatch.setattr(coding_agents, "run", synthetic_agent)
    admin(client)

    # Insert an existing user task
    with db.get_connection() as connection:
        tid = connection.execute(
            "INSERT INTO tasks_cache(source,title,status,priority,category,reason,external_id,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            ("local", "既存タスク", "todo", "High", "life", "手動登録", "ext-1", db.now_iso())
        ).lastrowid

    # Create job with explicit task_id
    payload = {"request_id": "web-explicit-task", "repository": str(repository), "provider": "codex", "goal": "既存タスク連携", "task_id": tid}
    job_id = client.post("/api/coding/jobs", json=payload).json()["job_id"]
    job = jobs.get(job_id)
    assert job["task_id"] == tid

    # Set external_id to petit-coding:job_id to test completion link
    with db.get_connection() as connection:
        connection.execute("UPDATE tasks_cache SET external_id=? WHERE id=?", ("petit-coding:" + job_id, tid))

    assert client.post(f"/api/coding/jobs/{job_id}/approve").status_code == 200
    jobs.pump()
    completed = client.post(f"/api/coding/jobs/{job_id}/complete").json()
    assert completed["status"] == "completed"
    assert completed["task_id"] == tid

    with db.get_connection() as connection:
        assert connection.execute("SELECT status FROM tasks_cache WHERE id=?", (tid,)).fetchone()[0] == "done"


def test_schema_migration_task_id_nullable(tmp_path, monkeypatch):
    test_db = tmp_path / "test_migration.db"
    monkeypatch.setattr(config, "DB_PATH", test_db)

    # Initialize a database with the old NOT NULL constraint
    with closing(sqlite3.connect(test_db)) as conn:
        conn.execute("""
        CREATE TABLE coding_jobs (
         id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, input_hash TEXT NOT NULL, task_id INTEGER NOT NULL,
         project_id TEXT, repository TEXT NOT NULL, base_commit TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
         goal TEXT NOT NULL, status TEXT NOT NULL, workspace TEXT, branch TEXT, summary TEXT NOT NULL DEFAULT '',
         checks_json TEXT NOT NULL DEFAULT '{}', error TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0,
         created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )
        """)
        conn.execute("INSERT INTO coding_jobs VALUES ('job-old', 'req-old', 'hash', 123, NULL, 'repo', 'commit', 'codex', 'model', 'goal', 'queued', NULL, NULL, '', '{}', NULL, 0, '2026-01-01', '2026-01-01')")
        conn.commit()

        info_before = conn.execute("PRAGMA table_info(coding_jobs)").fetchall()
        task_id_before = [col for col in info_before if col[1] == "task_id"][0]
        assert task_id_before[3] == 1  # notnull is True

    # Call ensure_schema which runs _migrate_task_id_nullable
    jobs.ensure_schema()

    with closing(sqlite3.connect(test_db)) as conn:
        info_after = conn.execute("PRAGMA table_info(coding_jobs)").fetchall()
        task_id_after = [col for col in info_after if col[1] == "task_id"][0]
        assert task_id_after[3] == 0  # notnull is now False

        # Verify old row is intact
        old_row = conn.execute("SELECT id, task_id FROM coding_jobs WHERE id='job-old'").fetchone()
        assert old_row == ("job-old", 123)

        # Verify new insert with NULL task_id succeeds
        conn.execute("INSERT INTO coding_jobs (id, request_id, input_hash, task_id, repository, base_commit, provider, model, goal, status, created_at, updated_at) VALUES ('job-new', 'req-new', 'hash2', NULL, 'repo', 'commit', 'codex', 'model', 'goal', 'queued', '2026-01-02', '2026-01-02')")
        new_row = conn.execute("SELECT id, task_id FROM coding_jobs WHERE id='job-new'").fetchone()
        assert new_row == ("job-new", None)


