"""Authenticated Web entrypoints for approved local coding jobs."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ConfigDict
from typing import Literal

from . import coding_jobs as jobs, setup_store as settings, setup_api, db

router = APIRouter(prefix="/api/coding", tags=["coding"], dependencies=[Depends(setup_api._admin)])


class Repositories(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paths: list[str] = Field(max_length=8)


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1, max_length=200)
    repository: str = Field(min_length=1, max_length=1000)
    goal: str = Field(min_length=1, max_length=8000)
    provider: Literal["codex", "antigravity_cli"]
    base_commit: str | None = Field(default=None, pattern="^[0-9a-f]{40,64}$")
    task_id: int | None = None
    project_id: str | None = Field(default=None, max_length=200)


def call(function, *args, **kwargs):
    try:return function(*args, **kwargs)
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc) if isinstance(exc, ValueError) else "リポジトリまたは保存場所へアクセスできません。") from None


@router.get("/config")
def config():
    jobs.ensure_schema()
    return {"repositories": jobs.roots(), "providers": ["codex", "antigravity_cli"],
            "policy": "source_HEAD_copy_only_no_shell_delete_push_or_merge"}


@router.put("/config", dependencies=[Depends(setup_api._same_origin)])
def configure(payload: Repositories):
    paths = [str(call(jobs.validate_repository, path)) for path in payload.paths]
    if len(paths) != len(set(paths)):raise HTTPException(400, "リポジトリが重複しています。")
    settings.update({"coding_roots": paths})
    return config()


@router.get("/jobs")
def listing():return {"jobs": jobs.list_jobs()}


@router.post("/jobs", dependencies=[Depends(setup_api._same_origin)])
def propose(payload: Proposal):
    return call(jobs.create, **payload.model_dump())


@router.get("/jobs/{job_id}")
def detail(job_id: str):return call(jobs.get, job_id)


@router.post("/jobs/{job_id}/approve", dependencies=[Depends(setup_api._same_origin)])
def approve(job_id: str):return call(jobs.approve, job_id)


@router.post("/jobs/{job_id}/cancel", dependencies=[Depends(setup_api._same_origin)])
def cancel(job_id: str):return call(jobs.cancel, job_id)


@router.get("/jobs/{job_id}/diff")
def diff(job_id: str):
    job = call(jobs.get, job_id)
    if not job["workspace"]:return {"files": [], "diff": "", "truncated": False}
    changed = call(jobs.changed, job["workspace"])
    pieces = []
    for name in changed:
        path = call(jobs.path_for, job["workspace"], name)
        tracked = jobs.git(job["workspace"], "ls-files", "--", name).strip()
        if tracked:
            pieces.append(jobs.git(job["workspace"], "diff", "--no-ext-diff", "--no-textconv", "--", name))
        else:
            pieces.append("New file: " + name + "\n" + path.read_bytes()[:50000].decode("utf-8", "replace") + "\n")
    text = "\n".join(pieces)
    return {"files": changed, "diff": text[:100000], "truncated": len(text) > 100000}


@router.post("/jobs/{job_id}/complete", dependencies=[Depends(setup_api._same_origin)])
def complete(job_id: str):
    job = call(jobs.get, job_id)
    if job["status"] != "ready_for_review":raise HTTPException(409, "静的チェック成功後のレビュー待ちタスクだけ完了にできます。")
    validation = call(jobs.checks, job["workspace"])
    if not validation["ok"]:raise HTTPException(409, "現在の差分に静的チェックの失敗があります。")
    jobs.finish(job_id, "completed", summary=job["summary"], checks=validation)
    with db.get_connection() as connection:
        connection.execute("UPDATE tasks_cache SET status='done',done_date=?,updated_at=? WHERE id=? AND source='local' AND external_id=?",
            (db.now_iso(), db.now_iso(), job["task_id"], "petit-coding:" + job_id))
    return jobs.get(job_id)
