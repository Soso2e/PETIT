"""Develop workspace contract: synthetic repositories/CLI only."""
from backend import coding_jobs, db
from tests.test_coding_jobs import repository, client, development_quota
from tests.test_setup_integrations import isolated, admin


def test_repo_workspace_threads_and_direct_job_link(repository, client, development_quota):
    assert client.get("/api/coding/threads").status_code == 401
    admin(client)
    root = str(repository)

    # Explicit thread IDs make retries safe, without orphaning duplicate threads.
    payload = {"thread_id": "dev-thread-1", "repository": root, "title": "AI統合を改善"}
    first = client.post("/api/coding/threads", json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["repository"] == root
    repeat = client.post("/api/coding/threads", json=payload)
    assert repeat.status_code == 200
    assert repeat.json()["thread_id"] == first.json()["thread_id"]

    created = client.post("/api/coding/jobs/start", json={
        "thread_id": "dev-thread-1", "request_id": "dev-request-1",
        "repository": root, "goal": "Repoのテストを修正", "model_key": "codex_sol"
    })
    assert created.status_code == 200, created.text
    job = created.json()
    assert job["status"] == "queued"

    thread = client.get("/api/coding/threads/dev-thread-1").json()
    assert thread["title"] == "AI統合を改善"
    assert [item["id"] for item in thread["jobs"]] == [job["id"]]
    assert thread["jobs"][0]["goal"] == "Repoのテストを修正"

    rows = client.get("/api/coding/threads", params={"repository": root}).json()["threads"]
    assert len(rows) == 1
    assert rows[0]["latest_job"]["provider"] == "codex"
    assert rows[0]["latest_job"]["latest_message"] == "Repoのテストを修正"

    workspace = client.get("/api/coding/workspaces").json()["repositories"]
    assert len(workspace) == 1
    assert workspace[0]["path"] == root
    assert workspace[0]["thread_count"] == 1
    assert workspace[0]["latest_job"]["id"] == job["id"]
    assert workspace[0]["mode"] == "git"


def test_repositoryless_thread_attach_and_cross_repo_guard(repository, client, development_quota, tmp_path):
    admin(client)
    root = str(repository)
    outside = tmp_path / "other"
    outside.mkdir()
    # Unregistered repo is never silently accepted as a workspace.
    assert client.post("/api/coding/threads", json={
        "thread_id": "illegal", "repository": str(outside), "title": "NG"
    }).status_code == 400

    thread = client.post("/api/coding/threads", json={
        "thread_id": "new-work", "repository": "", "title": "小さな試作"
    }).json()
    assert thread["repository"] == ""
    first = client.post("/api/coding/jobs/start", json={
        "thread_id": "new-work", "request_id": "work-1", "repository": "",
        "goal": "PCを調査", "model_key": "codex_sol"
    })
    assert first.status_code == 200, first.text
    assert client.get("/api/coding/threads", params={"repository": ""}).json()["threads"][0]["thread_id"] == "new-work"

    # A bound thread cannot be used to write a job for a different repository.
    assert client.post("/api/coding/jobs/start", json={
        "thread_id": "new-work", "request_id": "work-bad", "repository": root,
        "goal": "意図しない領域", "model_key": "codex_sol"
    }).status_code == 400

    bound = client.post("/api/coding/threads/new-work/repository", json={"repository": root})
    assert bound.status_code == 200, bound.text
    assert bound.json()["repository"] == root
    second = client.post("/api/coding/jobs/start", json={
        "thread_id": "new-work", "request_id": "work-2", "repository": root,
        "goal": "Gitの処理を直す", "model_key": "codex_sol"
    })
    assert second.status_code == 200, second.text
    jobs = client.get("/api/coding/threads/new-work").json()["jobs"]
    assert [item["repository"] for item in jobs] == ["", root]
    assert client.post("/api/coding/threads/new-work/repository", json={"repository": str(outside)}).status_code == 400


def test_legacy_jobs_remain_unassigned(repository, client, development_quota):
    admin(client)
    old = client.post("/api/coding/jobs/start", json={
        "request_id": "legacy", "repository": str(repository), "goal": "古い依頼",
        "model_key": "codex_sol"
    })
    assert old.status_code == 200
    assert client.get("/api/coding/threads", params={"repository": str(repository)}).json()["threads"] == []
    assert len(client.get("/api/coding/jobs").json()["jobs"]) == 1


def test_cli_receives_only_same_thread_handoff_and_no_unmerged_checkout_claim(repository, client, development_quota):
    admin(client)
    root = str(repository)
    for thread_id in ("handoff", "unrelated"):
        response = client.post("/api/coding/threads", json={
            "thread_id": thread_id, "repository": root, "title": thread_id
        })
        assert response.status_code == 200

    def submit(thread_id, request_id, goal):
        response = client.post("/api/coding/jobs/start", json={
            "thread_id": thread_id, "request_id": request_id,
            "repository": root, "goal": goal, "model_key": "codex_sol"
        })
        assert response.status_code == 200, response.text
        return response.json()

    prior = submit("handoff", "handoff-first", "1回目の依頼")
    other = submit("unrelated", "other-first", "OTHER_THREAD_SECRET_MARKER")
    with db.get_connection() as connection:
        connection.execute("UPDATE coding_jobs SET summary='変更案を作成した' WHERE id=?", (prior["id"],))
        connection.execute("UPDATE coding_jobs SET summary='UNRELATED_SUMMARY_SENTINEL' WHERE id=?", (other["id"],))

    next_job = submit("handoff", "handoff-second", "前回の続き")
    handoff = coding_jobs.development_context(coding_jobs.get(next_job["id"]))
    assert "1回目の依頼" in handoff and "変更案を作成した" in handoff
    assert "前回の続き" in handoff and "未統合変更" in handoff
    assert "OTHER_THREAD_SECRET_MARKER" not in handoff
    assert "UNRELATED_SUMMARY_SENTINEL" not in handoff


def test_chat_originated_job_surfaces_in_develop_threads(repository, client, development_quota):
    admin(client)
    from backend import conversation_store, development_threads
    root = str(repository)

    # Simulate normal chat thread (source: "desktop")
    conversation_store.create_thread("chat-thread-1", source="desktop", title="")

    # Create development job originating from chat
    job = coding_jobs.create_development(
        "chat-req-1", root, "Notion競合調査ジョブ", "codex_sol",
        thread_id="chat-thread-1", turn_id="turn-1"
    )
    assert job["id"]

    # Thread should be projected into develop threads
    threads = development_threads.list_threads(repository=root)
    assert any(t["thread_id"] == "chat-thread-1" for t in threads)
    target = next(t for t in threads if t["thread_id"] == "chat-thread-1")
    assert target["title"] == "Notion競合調査ジョブ"
    assert target["latest_job"]["id"] == job["id"]


def test_sync_chat_threads_backfills_unprojected_jobs(repository, client, development_quota):
    admin(client)
    from backend import conversation_store, development_threads
    root = str(repository)

    conversation_store.create_thread("legacy-chat-thread", source="web", title="")
    job = coding_jobs.create_development(
        "legacy-req-1", "", "PC全体のTurfLab調査ジョブ", "codex_sol",
        thread_id="legacy-chat-thread", turn_id="legacy-turn-1"
    )
    assert job["id"]

    # Deliberately remove develop projection to simulate pre-existing un-backfilled state
    with db.write_transaction() as connection:
        connection.execute("DELETE FROM coding_develop_threads WHERE thread_id='legacy-chat-thread'")

    # list_threads should automatically backfill via sync_chat_threads
    loose = development_threads.list_threads(repository="")
    assert any(t["thread_id"] == "legacy-chat-thread" for t in loose)
    target = next(t for t in loose if t["thread_id"] == "legacy-chat-thread")
    assert "TurfLab" in target["title"]


def test_register_conversation_thread_safe_with_unregistered_repo(client):
    admin(client)
    from backend import conversation_store, development_threads
    conversation_store.create_thread("unregistered-repo-thread", source="web", title="")

    # Passing invalid repository path should not raise, but fallback safely
    row = development_threads.register_conversation_thread(
        "unregistered-repo-thread",
        "C:\\NonExistent\\Arbitrary\\Path",
        title="安全な登録テスト"
    )
    assert row["thread_id"] == "unregistered-repo-thread"
    assert row["repository"] == ""


def test_jobs_create_with_thread_id_surfaces_in_develop(repository, client, monkeypatch):
    admin(client)
    from backend import conversation_store, development_threads, setup_store
    root = str(repository)

    # Allow codex
    cfg = setup_store.load()
    cfg.setdefault("brain", {})["permitted_models"] = ["codex"]
    setup_store.save(cfg)
    monkeypatch.setattr("backend.brain_priority.target", lambda p: {"configured": True, "model": "test-model"})

    conversation_store.create_thread("delegate-thread-1", source="web", title="")
    res = coding_jobs.create(
        "delegate-req-1", root, "直接委譲された開発ジョブ", "codex",
        approved=True, thread_id="delegate-thread-1", turn_id="turn-del-1"
    )
    assert res["job_id"]

    threads = development_threads.list_threads(repository=root)
    assert any(t["thread_id"] == "delegate-thread-1" for t in threads)
    target = next(t for t in threads if t["thread_id"] == "delegate-thread-1")
    assert target["title"] == "直接委譲された開発ジョブ"
