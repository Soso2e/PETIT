"""Authenticated Web entrypoints for approved local coding jobs."""
import asyncio
import json
import time
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ConfigDict
import os
from pathlib import Path
import subprocess
from typing import Literal

from . import coding_jobs as jobs, setup_store as settings, setup_api, db, development_models, development_pc, development_threads

router = APIRouter(prefix="/api/coding", tags=["coding"], dependencies=[Depends(setup_api._admin)])


class Repositories(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paths: list[str] = Field(max_length=64)


class Repository(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=1000)


class RepositoryExtra(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository: str = Field(min_length=1, max_length=1000)
    path: str = Field(min_length=1, max_length=1000)


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1, max_length=200)
    repository: str = Field(min_length=1, max_length=1000)
    goal: str = Field(min_length=1, max_length=8000)
    provider: Literal["codex", "antigravity_cli", "claude_code"]
    base_commit: str | None = Field(default=None, pattern="^[0-9a-f]{40,64}$")
    task_id: int | None = None
    project_id: str | None = Field(default=None, max_length=200)


class DevelopmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1, max_length=200)
    repository: str = Field(default="", max_length=1000)
    goal: str = Field(min_length=1, max_length=8000)
    model_key: Literal["auto", "claude_opus", "claude_sonnet", "codex_sol", "antigravity_hydrogen", "antigravity_neon"] = "auto"
    effort: Literal["low", "medium", "high"] = "medium"
    lightweight: bool = False
    thread_id: str | None = Field(default=None, min_length=1, max_length=200)


class DevelopThreadCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thread_id: str | None = Field(default=None, min_length=1, max_length=200)
    repository: str = Field(default="", max_length=1000)
    title: str = Field(default="", max_length=160)


class DevelopThreadAttach(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository: str = Field(min_length=1, max_length=1000)


class DevelopThreadUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=160)
    triage_status: Literal["active", "completed", "review_later"] | None = None


def call(function, *args, **kwargs):
    try:return function(*args, **kwargs)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        raise HTTPException(400, str(exc) if isinstance(exc, ValueError) else "リポジトリまたは保存場所へアクセスできません。") from None


@router.get("/config")
def config():
    jobs.ensure_schema()
    return {"repositories": jobs.roots(), "providers": ["codex", "antigravity_cli", "claude_code"],
            "models": [{"key": key, "label": value[2]} for key, value in development_models.MODELS.items()]}


@router.put("/config", dependencies=[Depends(setup_api._same_origin)])
def configure(payload: Repositories):
    paths = [_folder(path) for path in payload.paths]
    if len(paths) != len({os.path.normcase(path) for path in paths}):
        raise HTTPException(400, "フォルダが重複しています。")
    with settings._guard():
        settings.update({"coding_roots": paths})
    return config()


def _folder(value):
    path = Path(value)
    if not path.is_absolute():
        raise HTTPException(400, "サーバーPC上の絶対パスを指定してください。")
    path = call(jobs.project_workspaces._safe_root, path)
    call(development_pc.host_path, str(path), directory=True)
    return str(path)


@router.post("/config/root", dependencies=[Depends(setup_api._same_origin)])
def add_folder(payload: Repository):
    path = _folder(payload.path)
    with settings._guard():
        paths = settings.load()["coding_roots"]
        if os.path.normcase(path) not in {os.path.normcase(item) for item in paths}:
            if len(paths) >= 64:
                raise HTTPException(400, "設定から登録できるフォルダは64件までです。")
            settings.update({"coding_roots": [*paths, path]})
    return config()


@router.delete("/config/root", dependencies=[Depends(setup_api._same_origin)])
def remove_folder(payload: Repository):
    key = os.path.normcase(str(Path(payload.path).absolute()))
    with settings._guard():
        data = settings.load()
        paths = [p for p in data["coding_roots"] if os.path.normcase(str(Path(p).absolute())) != key]
        extras = {
            repo: items
            for repo, items in (data.get("coding_root_extras") or {}).items()
            if os.path.normcase(str(Path(repo).absolute())) != key
        }
        settings.update({"coding_roots": paths, "coding_root_extras": extras})
    return config()


@router.post("/config/root/extra", dependencies=[Depends(setup_api._same_origin)])
def add_extra_folder(payload: RepositoryExtra):
    repo_path = str(call(jobs.require_repository, payload.repository))
    extra_path = _folder(payload.path)
    if os.path.normcase(extra_path) == os.path.normcase(repo_path):
        raise HTTPException(400, "リポジトリ自身は追加フォルダに指定できません。")
    repo_key = os.path.normcase(repo_path)
    extra_key = os.path.normcase(extra_path)
    with settings._guard():
        raw_extras = dict(settings.load().get("coding_root_extras") or {})
        existing_key = next(
            (k for k in raw_extras if os.path.normcase(str(Path(k).expanduser().absolute())) == repo_key),
            repo_path,
        )
        items = list(raw_extras.get(existing_key) or [])
        if extra_key not in {os.path.normcase(str(Path(item).expanduser().absolute())) for item in items}:
            if len(items) >= 16:
                raise HTTPException(400, "1つのリポジトリに追加できるフォルダは16件までです。")
            items.append(extra_path)
        raw_extras[existing_key] = items
        settings.update({"coding_root_extras": raw_extras})
    return config()


@router.delete("/config/root/extra", dependencies=[Depends(setup_api._same_origin)])
def remove_extra_folder(payload: RepositoryExtra):
    repo_key = os.path.normcase(str(Path(payload.repository).expanduser().absolute()))
    extra_key = os.path.normcase(str(Path(payload.path).expanduser().absolute()))
    with settings._guard():
        raw_extras = dict(settings.load().get("coding_root_extras") or {})
        updated = {}
        for k, items in raw_extras.items():
            if os.path.normcase(str(Path(k).expanduser().absolute())) == repo_key:
                kept = [p for p in (items or []) if os.path.normcase(str(Path(p).expanduser().absolute())) != extra_key]
                if kept:
                    updated[k] = kept
            else:
                updated[k] = items
        settings.update({"coding_root_extras": updated})
    return config()


@router.get("/usage")
def usage():
    jobs.ensure_schema()
    quotas = development_models.usage()
    return {"models": quotas, "providers": development_models.provider_usage(quotas)}


@router.get("/activity")
def activity(limit: int = 30):
    """Authenticated, read-only status list; never creates coding jobs."""
    return jobs.activity_summary(limit)


@router.get("/workspaces")
def workspaces():
    return {"repositories": call(development_threads.repositories)}


@router.get("/threads")
def threads(repository: str | None = None):
    return {"threads": call(development_threads.list_threads, repository)}


@router.post("/threads", dependencies=[Depends(setup_api._same_origin)])
def create_thread(payload: DevelopThreadCreate):
    return call(development_threads.create, **payload.model_dump())


@router.get("/threads/{thread_id}")
def thread_detail(thread_id: str):
    return call(development_threads.detail, thread_id)


@router.patch("/threads/{thread_id}", dependencies=[Depends(setup_api._same_origin)])
def update_thread(thread_id: str, payload: DevelopThreadUpdate):
    return call(development_threads.update, thread_id, **payload.model_dump())


@router.delete("/threads/{thread_id}", dependencies=[Depends(setup_api._same_origin)])
def delete_thread(thread_id: str):
    return call(development_threads.delete, thread_id)


@router.post("/threads/{thread_id}/repository", dependencies=[Depends(setup_api._same_origin)])
def attach_thread(thread_id: str, payload: DevelopThreadAttach):
    return call(development_threads.attach_repository, thread_id, payload.repository)


@router.get("/jobs")
def listing(thread_id: str | None = None):return {"jobs": jobs.list_jobs(thread_id)}


@router.post("/jobs", dependencies=[Depends(setup_api._same_origin)])
def propose(payload: Proposal):
    return call(jobs.create, **payload.model_dump())


@router.post("/jobs/start", dependencies=[Depends(setup_api._same_origin)])
def start(payload: DevelopmentRequest):
    if payload.thread_id:
        call(development_threads.verify, payload.thread_id, payload.repository)
    return call(jobs.create_development, **payload.model_dump(), direct=True)


@router.get("/jobs/{job_id}")
def detail(job_id: str):return call(jobs.get, job_id)


@router.get("/jobs/{job_id}/stream")
async def stream(job_id: str, request: Request):
    from . import coding_stream
    initial = await asyncio.to_thread(jobs.progress_snapshot, job_id)
    if initial is None:
        raise HTTPException(404, "開発ジョブが見つかりません。")

    async def events():
        snapshot = initial
        previous_status = None
        last_phase = None
        cursor = 0
        draft_cursor = 0
        last_sent = time.monotonic()
        yield "retry: 3000\n\n"
        while not await request.is_disconnected():
            if snapshot is None:
                return
            status, changes = snapshot
            for seq, phase in changes or ([(cursor, None)] if status != previous_status else []):
                cursor = seq
                if phase:
                    last_phase = phase
                data = json.dumps({"status": status, "phase": phase}, ensure_ascii=False)
                yield f"event: progress\ndata: {data}\n\n"
                last_sent = time.monotonic()
            draft_snap = coding_stream.snapshot(job_id)
            if draft_snap["seq"] != draft_cursor:
                draft_cursor = draft_snap["seq"]
                payload = json.dumps({
                    "status": status,
                    "phase": last_phase,
                    "tool": draft_snap["tool"],
                    "draft": draft_snap["draft"],
                    "thought": draft_snap["thought"],
                    "activity": draft_snap["activity"],
                }, ensure_ascii=False)
                yield f"event: draft\ndata: {payload}\n\n"
                last_sent = time.monotonic()
            if status not in {"queued", "running"}:
                return
            previous_status = status
            if time.monotonic() - last_sent > 15:
                yield ": keepalive\n\n"
                last_sent = time.monotonic()
            await asyncio.sleep(0.15)
            snapshot = await asyncio.to_thread(jobs.progress_snapshot, job_id, cursor)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.post("/jobs/{job_id}/approve", dependencies=[Depends(setup_api._same_origin)])
def approve(job_id: str):return call(jobs.approve, job_id)


@router.post("/jobs/{job_id}/cancel", dependencies=[Depends(setup_api._same_origin)])
def cancel(job_id: str):return call(jobs.cancel, job_id)


@router.post("/jobs/{job_id}/actions/{action_id}/{decision}", dependencies=[Depends(setup_api._same_origin)])
def resolve_action(job_id: str, action_id: str, decision: Literal["approve", "approve_always", "reject"]):
    return call(
        development_pc.resolve,
        call(jobs.get, job_id),
        action_id,
        decision in {"approve", "approve_always"},
        remember=decision == "approve_always",
    )


@router.get("/config/pc-whitelist")
def get_pc_whitelist():
    return development_pc.list_whitelist()


@router.delete("/config/pc-whitelist", dependencies=[Depends(setup_api._same_origin)])
def delete_pc_whitelist(signature: str):
    return {"user_whitelist": development_pc.remove_from_whitelist(signature)}


@router.get("/jobs/{job_id}/actions/{action_id}/preview")
def preview_action(job_id: str, action_id: str):
    return call(development_pc.preview, call(jobs.get, job_id), action_id)


def _diff_entry(name, text, untracked=False):
    """Per-file summary for the review list: status and line counts, diff body on demand in the UI."""
    lines = text.splitlines()
    if untracked:
        body = lines[1:-1] if lines[-1:] == [""] else lines[1:]
        status, additions, deletions = "added", len(body), 0
    else:
        status = ("added" if any(line.startswith("new file mode") for line in lines[:6])
                  else "deleted" if any(line.startswith("deleted file mode") for line in lines[:6]) else "modified")
        additions = sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
        deletions = sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
    binary = any(line.startswith("Binary files ") for line in lines[:8])
    return {"path": name, "status": status, "additions": additions, "deletions": deletions,
            "binary": binary, "diff": text, "truncated": False}


@router.get("/jobs/{job_id}/diff")
def diff(job_id: str):
    job = call(jobs.get, job_id)
    if not job["workspace"]:return {"files": [], "diff": "", "truncated": False, "entries": []}
    if job.get("mode") == "pc":
        from pathlib import Path
        from itertools import islice
        root = Path(job["workspace"])
        files = [str(path.relative_to(root)) for path in islice(root.rglob("*"), 1000) if path.is_file()]
        entries = [{"path": name, "status": "file", "additions": None, "deletions": None,
                    "binary": False, "diff": "", "truncated": False} for name in files]
        return {"files": files, "diff": "", "truncated": False, "entries": entries}
    base = job["base_commit"] if job.get("mode") == "git" else "HEAD"
    changed = call(jobs.changed, job["workspace"], base)
    pieces = []
    visible_files = []
    entries = []
    budget = 100000
    for name in changed:
        try:
            path = jobs.path_for(job["workspace"], name)
        except (ValueError, OSError):
            continue
        visible_files.append(name)
        tracked = jobs.git(job["workspace"], "ls-files", "--", name).strip()
        untracked = not (tracked or not path.exists())
        if untracked:
            piece = "New file: " + name + "\n" + path.read_bytes()[:50000].decode("utf-8", "replace") + "\n"
        else:
            piece = jobs.git(job["workspace"], "diff", "--no-ext-diff", "--no-textconv", base, "--", name)
        pieces.append(piece)
        entry = _diff_entry(name, piece, untracked)
        # Counts cover the whole file; only the body shown in the list shares the response budget.
        if len(piece) > budget:
            entry.update(diff=piece[:budget], truncated=True)
        budget -= len(entry["diff"])
        entries.append(entry)
    text = "\n".join(pieces)
    return {"files": visible_files, "diff": text[:100000], "truncated": len(text) > 100000, "entries": entries}


@router.post("/jobs/{job_id}/complete", dependencies=[Depends(setup_api._same_origin)])
def complete(job_id: str):
    job = call(jobs.get, job_id)
    if job["status"] != "ready_for_review":raise HTTPException(409, "静的チェック成功後のレビュー待ちタスクだけ完了にできます。")
    validation = {**job["checks"], "tests": job["tests"]}
    jobs.finish(job_id, "completed", summary=job["summary"], checks=validation)
    if job.get("task_id"):
        with db.get_connection() as connection:
            connection.execute("UPDATE tasks_cache SET status='done',done_date=?,updated_at=? WHERE id=? AND source='local' AND external_id=?",
                (db.now_iso(), db.now_iso(), job["task_id"], "petit-coding:" + job_id))
    return jobs.get(job_id)
