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
