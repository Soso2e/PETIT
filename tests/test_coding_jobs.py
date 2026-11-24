"""Local fixture repositories/DB only; mock agents are not live CLI acceptance."""
import hashlib
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import threading
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
    entry, = diff["entries"]
    assert (entry["path"], entry["status"], entry["additions"], entry["deletions"]) == ("main.py", "modified", 1, 1)
    assert "+VALUE = 2" in entry["diff"] and entry["truncated"] is False
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


def test_develop_direct_reviews_committed_native_cli_changes(repository, client, development_quota, monkeypatch):
    admin(client)
    (repository / "test_main.py").write_text(
        "import unittest\nfrom main import VALUE\n\n"
        "class TestValue(unittest.TestCase):\n"
        "    def test_new_value(self):\n"
        "        self.assertEqual(VALUE, 2)\n", encoding="utf-8")
    jobs.git(repository, "add", "test_main.py")
    jobs.git(repository, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "add test")
    observed = {}

    def agent(provider, target, goal, workspace, check, progress, *, resume=None, on_session=None):
        assert provider == "codex" and resume is None
        check()
        observed["target"] = (target["model"], target["effort"])
        (workspace / "main.py").write_text("VALUE = 2\n", encoding="utf-8")
        jobs.git(workspace, "add", "main.py")
        jobs.git(workspace, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "Update fixture")
        assert not jobs.git(workspace, "remote").strip()
        return "fixture"

    monkeypatch.setattr(coding_agents, "run_git", agent)
    payload = {"request_id": "direct", "repository": str(repository), "goal": "合成変更", "effort": "high"}
    job = client.post("/api/coding/jobs/start", json=payload).json()
    assert job["status"] == "queued"
    assert client.post("/api/coding/jobs/start", json=payload).json()["id"] == job["id"]
    assert jobs.pump()
    detail = jobs.get(job["id"])
    assert observed["target"] == ("gpt-6.2-sol", "high")
    assert detail["status"] == "ready_for_review" and detail["tests"] == "not_verified", detail["error"]
    result = client.get(f"/api/coding/jobs/{job['id']}/diff").json()
    assert result["files"] == ["main.py"] and "+VALUE = 2" in result["diff"]
    assert (repository / "main.py").read_text(encoding="utf-8") == "VALUE = 2\n"


def _native_recorder(calls, sessions, *, refuse=()):
    """Synthetic native CLI: appends one line per run and reports a session ID."""
    def agent(provider, target, goal, workspace, check, progress, *, resume=None, on_session=None):
        calls.append({"goal": goal, "workspace": workspace, "resume": resume})
        if resume in refuse:
            raise coding_agents.antigravity_cli_brain.CLIError("resume_unavailable", "synthetic")
        on_session(sessions.pop(0))
        with (workspace / "main.py").open("a", encoding="utf-8") as stream:
            stream.write("# run %d\n" % len(calls))
        return "run %d" % len(calls)
    return agent


def _thread_job(request_id, repository, goal, thread_id="develop-thread"):
    job = jobs.create_development(request_id, str(repository), goal, direct=True, thread_id=thread_id)
    assert jobs.pump()
    return jobs.get(job["id"])


def test_same_thread_continues_checkout_and_cli_session(repository, client, development_quota, monkeypatch):
    admin(client)
    calls = []
    monkeypatch.setattr(coding_agents, "run_git", _native_recorder(calls, ["session-1", "session-2"]))
    first = _thread_job("first", repository, "最初の依頼")
    second = _thread_job("second", repository, "続きの依頼")
    assert first["status"] == second["status"] == "ready_for_review", (first["error"], second["error"])
    assert second["workspace"] == first["workspace"] and second["branch"] == first["branch"]
    assert [call["resume"] for call in calls] == [None, "session-1"]
    # The resumed CLI already holds the conversation; only the new request is sent.
    assert calls[1]["goal"] == "続きの依頼"
    kinds = [item["kind"] for item in second["events"]]
    assert "workspace_continued" in kinds and "session_resumed" in kinds and "workspace_ready" not in kinds
    diff = client.get(f"/api/coding/jobs/{second['id']}/diff").json()["diff"]
    assert "+# run 1" in diff and "+# run 2" in diff
    with db.get_connection() as connection:
        saved = dict(connection.execute("SELECT job_id,session_id FROM coding_job_sessions").fetchall())
    assert saved == {first["id"]: "session-1", second["id"]: "session-2"}
    content = (repository / "main.py").read_text(encoding="utf-8")
    assert "# run 1" in content and "# run 2" in content


def test_refused_session_restarts_once_with_thread_summary(repository, development_quota, monkeypatch):
    calls = []
    monkeypatch.setattr(coding_agents, "run_git", _native_recorder(calls, ["old", "new"], refuse={"old"}))
    first = _thread_job("first", repository, "最初の依頼")
    second = _thread_job("second", repository, "続きの依頼")
    assert second["status"] == "ready_for_review", second["error"]
    assert [call["resume"] for call in calls] == [None, "old", None]
    assert "最初の依頼" in calls[2]["goal"] and "引き継いでいます" in calls[2]["goal"]
    assert calls[2]["workspace"] == Path(first["workspace"])
    assert "session_restarted" in [item["kind"] for item in second["events"]]


def test_other_thread_or_moved_repository_does_not_share_cli_session(repository, development_quota, monkeypatch):
    calls = []
    monkeypatch.setattr(coding_agents, "run_git", _native_recorder(calls, ["a", "b", "c"]))
    first = _thread_job("first", repository, "最初の依頼")
    other = _thread_job("other", repository, "別スレッド", thread_id="another-thread")
    assert other["workspace"] == first["workspace"] and calls[1]["resume"] is None
    (repository / "main.py").write_text("VALUE = 3\n", encoding="utf-8")
    jobs.git(repository, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qam", "move")
    moved = _thread_job("moved", repository, "続きの依頼")
    assert moved["status"] == "ready_for_review", moved["error"]
    assert moved["workspace"] == first["workspace"] and calls[2]["resume"] is None
    assert "前ジョブの未統合変更を引き継いだと仮定しないでください" in calls[2]["goal"]
    assert "workspace_ready" in [item["kind"] for item in moved["events"]]


def test_session_is_not_offered_to_another_cli(repository, development_quota, monkeypatch):
    calls = []
    monkeypatch.setattr(coding_agents, "run_git", _native_recorder(calls, ["codex-session", "agy-session"]))
    first = _thread_job("first", repository, "最初の依頼")
    with db.get_connection() as connection:
        connection.execute("UPDATE coding_jobs SET provider='antigravity_cli' WHERE id=?", (first["id"],))
    second = _thread_job("second", repository, "続きの依頼")
    assert second["workspace"] == first["workspace"] and calls[1]["resume"] is None
    assert "引き継いでいます" in calls[1]["goal"]


def _commit(repository, message):
    jobs.git(repository, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qam", message)


def test_commits_made_by_the_job_keep_the_thread_session(repository, development_quota, monkeypatch):
    calls = []
    recorder = _native_recorder(calls, ["session-1", "session-2"])

    def committing(provider, target, goal, workspace, check, progress, **options):
        summary = recorder(provider, target, goal, workspace, check, progress, **options)
        _commit(workspace, "job commit")
        return summary

    monkeypatch.setattr(coding_agents, "run_git", committing)
    first = _thread_job("first", repository, "最初の依頼")
    second = _thread_job("second", repository, "続きの依頼")
    assert first["status"] == second["status"] == "ready_for_review", (first["error"], second["error"])
    assert second["base_commit"] != first["base_commit"]
    assert [call["resume"] for call in calls] == [None, "session-1"] and calls[1]["goal"] == "続きの依頼"
    kinds = [item["kind"] for item in second["events"]]
    assert "workspace_continued" in kinds and "session_resumed" in kinds
    # Each review covers the commits since that job's own start.
    assert jobs.changed(second["workspace"], second["base_commit"]) == ["main.py"]
    diff = jobs.git(second["workspace"], "diff", second["base_commit"])
    assert "+# run 2" in diff and "+# run 1" not in diff


def test_restart_records_head_so_the_interrupted_session_continues(repository, development_quota, monkeypatch):
    calls = []
    monkeypatch.setattr(coding_agents, "run_git", _native_recorder(calls, ["session-2"]))
    first = jobs.create_development("first", str(repository), "最初の依頼", direct=True, thread_id="develop-thread")
    # The Core died while the CLI was working: it had reported its session and committed once.
    with db.get_connection() as connection:
        connection.execute("UPDATE coding_jobs SET status='running',workspace=? WHERE id=?", (str(repository), first["id"]))
    jobs.remember_session(first["id"], "session-1")
    (repository / "main.py").write_text("VALUE = 5\n", encoding="utf-8")
    _commit(repository, "work before the restart")
    try:
        jobs.start()
    finally:
        jobs.stop()
        jobs._stop.clear()
    assert jobs.get(first["id"])["status"] == "interrupted"
    second = _thread_job("second", repository, "続きから再開")
    assert second["status"] == "ready_for_review", second["error"]
    assert calls[0]["resume"] == "session-1" and calls[0]["goal"] == "続きから再開"




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


def test_checks_respect_global_autocrlf_and_still_detect_added_whitespace(repository, tmp_path, monkeypatch):
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text("[core]\n\tautocrlf = true\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    edited = repository / "notes.txt"
    edited.write_bytes(b"unchanged trailing space  \nold text\n")
    jobs.git(repository, "add", "--", edited.name)
    jobs.git(repository, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "baseline whitespace")
    edited.write_bytes(b"unchanged trailing space  \r\nnew text\r\n")
    assert jobs.checks(repository)["ok"]
    edited.write_bytes(b"unchanged trailing space  \r\nnew text  \r\n")
    assert jobs.checks(repository)["static"] == [{"kind": "diff_whitespace", "ok": False}]


def test_checks_and_diff_skip_protected_untracked_paths(repository, client):
    admin(client)
    head = jobs.git(repository, "rev-parse", "HEAD").strip()
    (repository / "storage").mkdir(exist_ok=True)
    (repository / "storage" / "uvicorn.log").write_text("runtime log\n", encoding="utf-8")
    (repository / ".gemini").mkdir(exist_ok=True)
    (repository / ".gemini" / "tmp.txt").write_text("scratch\n", encoding="utf-8")
    (repository / "main.py").write_text("VALUE = 42\n", encoding="utf-8")

    result = jobs.checks(str(repository), head)
    assert result["ok"] is True
    assert [item["path"] for item in result["static"] if "path" in item] == ["main.py"]

    job = jobs.create("diff-protected", str(repository), "確認", "antigravity_cli", base_commit=head)
    with db.get_connection() as connection:
        connection.execute("UPDATE coding_jobs SET workspace=?, status='ready_for_review' WHERE id=?",
                           (str(repository), job["job_id"]))
    response = client.get(f"/api/coding/jobs/{job['job_id']}/diff")
    assert response.status_code == 200
    payload = response.json()
    assert payload["files"] == ["main.py"]
    assert "VALUE = 42" in payload["diff"]


def test_coding_stream_emits_draft_and_tool_events(repository, client):
    from backend import coding_stream
    admin(client)
    job_id = jobs.create("draft-stream", str(repository), "進捗確認", "antigravity_cli")["job_id"]
    coding_stream.append_delta(job_id, "ファイルを解析しています。")
    coding_stream.publish_tool(job_id, "read_file")
    coding_stream.append_delta(job_id, "完了しました。")
    try:
        response = client.get(f"/api/coding/jobs/{job_id}/stream")
        assert response.status_code == 200
        assert "event: draft" in response.text
        assert "ファイルを解析しています。完了しました。" in response.text
    finally:
        coding_stream.clear(job_id)





def _notices():
    from backend import notifications
    notifications.init_db()
    with db.get_connection() as connection:
        return [dict(row) for row in connection.execute(
            "SELECT category,title,body,target_url FROM notification_events ORDER BY id")]


def test_finished_and_failed_jobs_notify_without_job_content(repository, development_quota, monkeypatch):
    calls = []
    monkeypatch.setattr(coding_agents, "run_git", _native_recorder(calls, ["session-1"]))
    done = _thread_job("first", repository, "秘密の依頼内容", thread_id="develop-thread/1")
    assert done["status"] == "ready_for_review"

    def broken(*args, **kwargs):
        raise ValueError("秘密のエラー詳細")

    monkeypatch.setattr(coding_agents, "run_git", broken)
    failed = _thread_job("second", repository, "続きの依頼", thread_id="develop-thread/1")
    assert failed["status"] == "failed"
    jobs.cancel(jobs.create_development("third", str(repository), "取消する依頼", direct=True)["id"])
    notices = _notices()
    assert [item["title"] for item in notices] == ["開発ジョブ: レビュー待ち", "開発ジョブ: 失敗"]
    assert {item["category"] for item in notices} == {"development"}
    # The link opens the thread; nothing from the request, the repository or the error is in the text.
    assert all(item["target_url"].startswith("/static/universe.html?view=development&dev_thread=develop-thread%2F1")
               for item in notices), notices
    text = json.dumps(notices, ensure_ascii=False)
    assert "秘密" not in text and str(repository) not in text and "main.py" not in text
    from backend import notifications
    assert notifications.DEFAULT_PREFERENCES["development"] is False


def test_notification_failure_never_changes_the_job(repository, development_quota, monkeypatch):
    from backend import notifications
    monkeypatch.setattr(notifications, "dispatch_notification", Mock(side_effect=RuntimeError("push down")))
    monkeypatch.setattr(coding_agents, "run_git", _native_recorder([], ["session-1"]))
    assert _thread_job("first", repository, "最初の依頼")["status"] == "ready_for_review"


def test_restart_announces_the_interrupted_job(repository):
    job_id = jobs.create("one", str(repository), "目的", "codex", approved=True)["job_id"]
    with db.get_connection() as connection:
        connection.execute("UPDATE coding_jobs SET status='running' WHERE id=?", (job_id,))
    try:
        jobs.start()
    finally:
        jobs.stop()
        jobs._stop.clear()
    assert [item["title"] for item in _notices()] == ["開発ジョブ: 再起動で中断"]


def test_complete_ignores_unrelated_whitespace_after_head_advances(repository, client, monkeypatch):
    admin(client)
    assert client.put("/api/coding/config", json={"paths": [str(repository)]}).status_code == 200
    monkeypatch.setattr(coding_agents, "run", synthetic_agent)
    payload = {"request_id": "web-whitespace", "repository": str(repository), "provider": "codex", "goal": "合成変更"}
    job_id = client.post("/api/coding/jobs", json=payload).json()["job_id"]
    assert client.post(f"/api/coding/jobs/{job_id}/approve").status_code == 200
    jobs.pump()
    assert jobs.get(job_id)["status"] == "ready_for_review"

    # Simulate another commit advancing the workspace with a trailing blank line.
    workspace = Path(jobs.get(job_id)["workspace"])
    (workspace / "extra.md").write_text("line\n\n", encoding="utf-8")
    jobs.git(workspace, "add", "extra.md")
    jobs.git(workspace, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "unrelated whitespace")

    response = client.post(f"/api/coding/jobs/{job_id}/complete")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed"


def test_pc_command_approval_resumes_with_output_and_grows_whitelist(repository, client, development_quota, monkeypatch, tmp_path):
    import sys
    admin(client)
    folder = tmp_path / "pc-cmd"
    folder.mkdir()
    assert client.post("/api/coding/config/root", json={"path": str(folder)}).status_code == 200

    seen_goals = []

    def agent(provider, target, goal, invoke, check, progress, **kwargs):
        seen_goals.append(goal)
        if len(seen_goals) == 1:
            proposed = invoke("run_pc_command", {
                "path": str(folder),
                "argv": [sys.executable, "-c", "print('pc-diag-output')"],
            })
            assert proposed["approval_required"] is True
            assert proposed["whitelist_candidate"].startswith("exe:")
            return "承認待ち"
        assert "pc-diag-output" in goal
        return "調査完了"

    monkeypatch.setattr(coding_agents, "run", agent)
    job = client.post("/api/coding/jobs/start", json={"request_id": "pc-cmd-1", "repository": str(folder), "goal": "診断"}).json()
    jobs.pump()
    detail = jobs.get(job["id"])
    assert detail["status"] == "waiting_approval"
    action_id = detail["actions"][0]["id"]

    resumed = client.post(f"/api/coding/jobs/{job['id']}/actions/{action_id}/approve_always")
    assert resumed.status_code == 200
    payload = resumed.json()
    assert payload["status"] == "applied"
    assert payload["resumed"] is True
    assert payload["whitelisted"]
    assert "pc-diag-output" in payload["result"]["stdout"]
    assert jobs.get(job["id"])["status"] == "queued"

    jobs.pump()
    finished = jobs.get(job["id"])
    assert finished["status"] == "ready_for_review"
    assert finished["summary"] == "調査完了"

    # Second job with the same command signature runs immediately without approval.
    seen_goals.clear()

    def agent_whitelisted(provider, target, goal, invoke, check, progress, **kwargs):
        res = invoke("run_pc_command", {
            "path": str(folder),
            "argv": [sys.executable, "-c", "print('pc-diag-second')"],
        })
        assert res["executed"] is True
        assert res["whitelisted"] is True
        assert "pc-diag-second" in res["stdout"]
        return "即実行完了"

    monkeypatch.setattr(coding_agents, "run", agent_whitelisted)
    job2 = client.post("/api/coding/jobs/start", json={"request_id": "pc-cmd-2", "repository": str(folder), "goal": "再診断"}).json()
    jobs.pump()
    assert jobs.get(job2["id"])["status"] == "ready_for_review"

    wl = client.get("/api/coding/config/pc-whitelist").json()
    assert payload["whitelisted"] in wl["user_whitelist"]
    deleted = client.request("DELETE", "/api/coding/config/pc-whitelist", params={"signature": payload["whitelisted"]})
    assert deleted.status_code == 200
    assert payload["whitelisted"] not in deleted.json()["user_whitelist"]


def test_repository_extra_folders_lifecycle_and_job_context(repository, client, development_quota, tmp_path, monkeypatch):
    admin(client)
    extra = tmp_path / "shared_assets"
    extra.mkdir()

    # Self-reference is rejected
    self_res = client.post("/api/coding/config/root/extra", json={"repository": str(repository), "path": str(repository)})
    assert self_res.status_code == 400

    # Add extra folder
    added = client.post("/api/coding/config/root/extra", json={"repository": str(repository), "path": str(extra)})
    assert added.status_code == 200
    repos = added.json()["repositories"]
    assert len(repos) == 1
    assert [e["path"] for e in repos[0]["extra_folders"]] == [str(extra.resolve())]

    # Workspaces endpoint exposes extra_folders too
    ws = client.get("/api/coding/workspaces").json()["repositories"]
    assert [e["path"] for e in ws[0]["extra_folders"]] == [str(extra.resolve())]

    # Running a git job passes extra_dirs to coding_agents.run_git and prompt
    seen = {}

    def fake_run_git(provider, target, goal, workspace, check, progress, *, resume=None, on_session=None, extra_dirs=()):
        seen["goal"] = goal
        seen["extra_dirs"] = list(extra_dirs)
        return "完了"

    monkeypatch.setattr(coding_agents, "run_git", fake_run_git)
    started = client.post("/api/coding/jobs/start", json={
        "request_id": "extra-1",
        "repository": str(repository),
        "goal": "共有アセットも確認して",
        "model_key": "codex_sol",
    })
    assert started.status_code == 200
    assert jobs.pump()
    assert seen["extra_dirs"] == [str(extra.resolve())]
    assert str(extra.resolve()) in seen["goal"]

    # Remove extra folder
    removed = client.request("DELETE", "/api/coding/config/root/extra", json={"repository": str(repository), "path": str(extra)})
    assert removed.status_code == 200
    assert removed.json()["repositories"][0]["extra_folders"] == []

    # Re-add and verify removing the repository cleans up coding_root_extras
    assert client.post("/api/coding/config/root/extra", json={"repository": str(repository), "path": str(extra)}).status_code == 200
    assert client.request("DELETE", "/api/coding/config/root", json={"path": str(repository)}).status_code == 200
    assert settings.load().get("coding_root_extras") == {}


def test_same_repository_waits_while_different_repositories_run_in_parallel(repository, tmp_path, development_quota, monkeypatch):
    repo2 = tmp_path / "repo2"
    repo2.mkdir()
    jobs.git(repo2, "init")
    jobs.git(repo2, "config", "user.name", "Fixture")
    jobs.git(repo2, "config", "user.email", "fixture@example.invalid")
    (repo2 / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    jobs.git(repo2, "add", "app.py")
    jobs.git(repo2, "commit", "-m", "initial")
    settings.update({"coding_roots": [str(repository), str(repo2)]})

    repo1_a_started = threading.Event()
    repo2_started = threading.Event()
    both_running_checked = threading.Event()
    release_repo1_a = threading.Event()
    release_repo2 = threading.Event()
    repo1_a_second_observed_queued = []
    order_lock = threading.Lock()
    execution_order = []

    job_a1 = jobs.create_development("par-a1", str(repository), "A1", "codex_sol", direct=True)
    job_a2 = jobs.create_development("par-a2", str(repository), "A2", "codex_sol", direct=True)
    job_b1 = jobs.create_development("par-b1", str(repo2), "B1", "codex_sol", direct=True)

    def fake_run_git(provider, target, goal, workspace, check, progress, *, resume=None, on_session=None, extra_dirs=()):
        with order_lock:
            execution_order.append(goal)
        if goal == "A1":
            repo1_a_started.set()
            assert repo2_started.wait(timeout=5), "Different repository job B1 should run in parallel with A1"
            repo1_a_second_observed_queued.append(jobs.get(job_a2["id"])["status"])
            both_running_checked.set()
            assert release_repo1_a.wait(timeout=5)
        elif goal == "B1":
            repo2_started.set()
            assert repo1_a_started.wait(timeout=5), "Different repository job A1 should run in parallel with B1"
            assert release_repo2.wait(timeout=5)
        return f"done:{goal}"

    monkeypatch.setattr(coding_agents, "run_git", fake_run_git)
    jobs.start()
    try:
        assert repo1_a_started.wait(timeout=5)
        assert repo2_started.wait(timeout=5)
        assert both_running_checked.wait(timeout=5)
        assert repo1_a_second_observed_queued == ["queued"]
        assert jobs.get(job_a2["id"])["status"] == "queued"

        release_repo2.set()
        release_repo1_a.set()

        b1_done = jobs.wait_for_job(job_b1["id"], timeout=5, poll_interval=0.05)
        a1_done = jobs.wait_for_job(job_a1["id"], timeout=5, poll_interval=0.05)
        a2_done = jobs.wait_for_job(job_a2["id"], timeout=5, poll_interval=0.05)
        assert b1_done["status"] == "ready_for_review"
        assert a1_done["status"] == "ready_for_review"
        assert a2_done["status"] == "ready_for_review"
        assert execution_order.index("A1") < execution_order.index("A2")
    finally:
        release_repo1_a.set()
        release_repo2.set()
        jobs.stop()


def test_claim_next_skips_busy_repository_and_allows_empty_repository_pc_jobs(repository, tmp_path, development_quota, monkeypatch):
    repo2 = tmp_path / "repo2_sync"
    repo2.mkdir()
    jobs.git(repo2, "init")
    jobs.git(repo2, "config", "user.name", "Fixture")
    jobs.git(repo2, "config", "user.email", "fixture@example.invalid")
    (repo2 / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    jobs.git(repo2, "add", "app.py")
    jobs.git(repo2, "commit", "-m", "initial")
    settings.update({"coding_roots": [str(repository), str(repo2)]})

    j1 = jobs.create_development("claim-1", str(repository), "R1-1", "codex_sol", direct=True)["id"]
    j2 = jobs.create_development("claim-2", str(repository), "R1-2", "codex_sol", direct=True)["id"]
    j3 = jobs.create_development("claim-3", str(repo2), "R2-1", "codex_sol", direct=True)["id"]
    j4 = jobs.create_development("claim-4", "", "PC-1", "codex_sol", direct=True)["id"]
    j5 = jobs.create_development("claim-5", "", "PC-2", "codex_sol", direct=True)["id"]

    assert jobs.claim_next() == j1
    # j2 shares repository with running j1, so claim_next skips j2 and picks j3
    assert jobs.claim_next() == j3
    # PC jobs without a repository are not blocked by each other
    assert jobs.claim_next() == j4
    assert jobs.claim_next() == j5
    # Only j2 remains queued, and its repository is still running
    assert jobs.claim_next() is None

    jobs.finish(j1, "ready_for_review", summary="done")
    assert jobs.claim_next() == j2
