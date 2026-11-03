"""Durable, approved CLI coding jobs over isolated local repository copies."""
from __future__ import annotations

import ast
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import threading
import time
from uuid import uuid4

from . import config, db, setup_store as settings, project_workspaces, brain_priority, coding_agents

_lock = threading.RLock()
_stop = threading.Event()
_worker = None
TERMINAL = {"completed", "failed", "cancelled", "interrupted", "ready_for_review", "checks_failed"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS coding_jobs (
 id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, input_hash TEXT NOT NULL, task_id INTEGER NOT NULL,
 project_id TEXT, repository TEXT NOT NULL, base_commit TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
 goal TEXT NOT NULL, status TEXT NOT NULL, workspace TEXT, branch TEXT, summary TEXT NOT NULL DEFAULT '',
 checks_json TEXT NOT NULL DEFAULT '{}', error TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS coding_job_events (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, kind TEXT NOT NULL,
 detail TEXT NOT NULL, created_at TEXT NOT NULL
);
"""


def ensure_schema():
    with _lock, db.get_connection() as connection:
        if connection.execute("SELECT 1 FROM sqlite_master WHERE name='coding_jobs'").fetchone():return
        if db._transaction.get() is not None:
            raise ValueError("開発タスク画面を開いて初期化してください。")
        backup = Path(str(config.DB_PATH) + ".before-coding-jobs.bak")
        if not backup.exists():
            with closing(sqlite3.connect(backup)) as destination:
                connection.backup(destination)
                if destination.execute("PRAGMA quick_check").fetchone()[0] != "ok":raise ValueError("backup_check_failed")
        connection.executescript(SCHEMA)


def git(root, *args):
    from .antigravity_cli_brain import environment
    result = subprocess.run(["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-C", str(root), *args],
        capture_output=True, timeout=45, env=environment(), **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
    if result.returncode:raise ValueError("Git操作に失敗しました。リポジトリと開始コミットを確認してください。")
    return result.stdout.decode("utf-8", "replace")


def validate_repository(path):
    root = project_workspaces._safe_root(Path(path))
    if root == root.parent or "_private" in {p.casefold() for p in root.parts}:raise ValueError("invalid_repository")
    if Path(git(root, "rev-parse", "--show-toplevel").strip()).resolve() != root:raise ValueError("Gitルートを指定してください。")
    return root


def roots():
    result = []
    for path in settings.load().get("coding_roots", []):
        try:
            root = validate_repository(path)
            result.append({"path": str(root), "name": root.name, "head": git(root, "rev-parse", "HEAD").strip()})
        except (ValueError, OSError, subprocess.SubprocessError):
            result.append({"path": path, "name": Path(path).name, "error": "参照できないGitルートです。"})
    return result


def require_repository(path):
    root = project_workspaces._safe_root(Path(path))
    allowed = []
    for configured in settings.load().get("coding_roots", []):
        try:allowed.append(os.path.normcase(str(project_workspaces._safe_root(Path(configured)))))
        except (ValueError, OSError):continue
    if os.path.normcase(str(root)) not in allowed:raise ValueError("開発用に明示許可したリポジトリを指定してください。")
    return root


def event(job_id, kind, detail=""):
    with db.get_connection() as connection:
        connection.execute("INSERT INTO coding_job_events(job_id,kind,detail,created_at) VALUES(?,?,?,?)",
            (job_id, kind, detail[:2000], db.now_iso()))


def get(job_id):
    ensure_schema()
    with db.get_connection() as connection:
        row = connection.execute("SELECT * FROM coding_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:raise ValueError("開発タスクが見つかりません。")
        result = dict(row)
        result["checks"] = json.loads(result.pop("checks_json"))
        result["events"] = [dict(x) for x in connection.execute(
            "SELECT seq,kind,detail,created_at FROM coding_job_events WHERE job_id=? ORDER BY seq DESC LIMIT 80", (job_id,))][::-1]
    result["tests"] = "not_run"
    result["host_acceptance"] = "not_verified"
    return result


def list_jobs():
    ensure_schema()
    with db.get_connection() as connection:
        ids = [r[0] for r in connection.execute("SELECT id FROM coding_jobs ORDER BY created_at DESC LIMIT 50")]
    return [get(x) for x in ids]


def create(request_id, repository, goal, provider, *, approved=False, task_id=None, project_id=None, base_commit=None):
    ensure_schema()
    if provider not in {"codex", "antigravity_cli"}:raise ValueError("開発用CLIを選択してください。")
    if not goal.strip() or len(goal) > 8000:raise ValueError("開発目的を1〜8000文字で指定してください。")
    root = require_repository(repository)
    payload = json.dumps([str(root), goal, provider, task_id, project_id, base_commit], ensure_ascii=False)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    with db.write_transaction() as connection:
        previous = connection.execute("SELECT id,input_hash FROM coding_jobs WHERE request_id=?", (request_id,)).fetchone()
        if previous:
            if previous["input_hash"] != digest:raise ValueError("同じ依頼IDに異なる入力は指定できません。")
            return {"job_id": previous["id"], "reused": True}
        data = settings.load()
        if not brain_priority.permitted(provider, data) or not brain_priority.target(provider)["configured"]:
            raise ValueError("選択したCLIを初期設定で接続してください。")
        if task_id is not None and not connection.execute("SELECT 1 FROM tasks_cache WHERE id=?", (task_id,)).fetchone():
            raise ValueError("対象Task IDが見つかりません。")
        if project_id:
            from . import project_continuity
            if project_continuity.get_project(project_id) is None:raise ValueError("対象Project IDが見つかりません。")
        job_id, now = uuid4().hex, db.now_iso()
        head = git(root, "rev-parse", "HEAD").strip()
        if base_commit is not None and base_commit != head:raise ValueError("開始コミットが変わりました。対象を更新してください。")
        if task_id is None:
            task_id = connection.execute("INSERT INTO tasks_cache(source,title,status,priority,category,reason,external_id,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                ("local", goal.strip()[:200], "todo", "High", "development", "CLI開発タスク / " + job_id, "petit-coding:" + job_id, now)).lastrowid
        connection.execute("INSERT INTO coding_jobs(id,request_id,input_hash,task_id,project_id,repository,base_commit,provider,model,goal,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (job_id, request_id, digest, task_id, project_id, str(root), head, provider,
             brain_priority.target(provider).get("model") or "", goal, "queued" if approved else "proposed", now, now))
    event(job_id, "queued" if approved else "proposed", "元checkoutの未コミット変更を含めず、HEADの専用コピーで作業します。")
    return {"job_id": job_id, "task_id": task_id, "created": True, "started": approved, "status": "queued" if approved else "proposed"}


def approve(job_id):
    job = get(job_id)
    root = require_repository(job["repository"])
    if git(root, "rev-parse", "HEAD").strip() != job["base_commit"]:raise ValueError("開始コミットが変わりました。新しい依頼で確認してください。")
    with db.get_connection() as connection:
        connection.execute("UPDATE coding_jobs SET status='queued',updated_at=? WHERE id=? AND status='proposed' AND cancel_requested=0", (db.now_iso(), job_id))
    return get(job_id)


def cancel(job_id):
    get(job_id)
    with db.get_connection() as connection:
        connection.execute("UPDATE coding_jobs SET cancel_requested=1,status=CASE WHEN status IN ('proposed','queued') THEN 'cancelled' ELSE status END,updated_at=? WHERE id=?", (db.now_iso(), job_id))
    return {"job_id": job_id, "cancel_requested": True}


def finish(job_id, status, *, summary="", checks=None, error=None):
    with db.get_connection() as connection:
        if status in {"ready_for_review", "checks_failed"}:
            row = connection.execute("SELECT cancel_requested FROM coding_jobs WHERE id=?", (job_id,)).fetchone()
            if row and row[0]:status = "cancelled"
        connection.execute("UPDATE coding_jobs SET status=?,summary=?,checks_json=?,error=?,updated_at=? WHERE id=?",
            (status, summary[:12000], json.dumps(checks or {}, ensure_ascii=False), error, db.now_iso(), job_id))
    event(job_id, status)


def path_for(workspace, name):
    relative = Path(name)
    if relative.is_absolute() or relative.drive or not relative.parts or ".." in relative.parts or ":" in str(relative):raise ValueError("invalid_relative_path")
    denied = {".git", "_private", ".venv", "node_modules", "storage", ".ssh", ".gemini", ".codex"}
    if any(x.casefold() in denied for x in relative.parts):raise ValueError("protected_path")
    if any(x.casefold().startswith(".env") and x.casefold() not in {".env.example", ".env.sample", ".env.template", ".env.dist"} for x in relative.parts):
        raise ValueError("credential_path")
    root = Path(workspace).resolve(strict=True)
    path = root / relative
    for item in (path, *path.parents):
        if item == root:break
        if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):raise ValueError("linked_path")
    if not path.resolve().is_relative_to(root):raise ValueError("outside_workspace")
    return path


def files(workspace):
    result = []
    for name in git(workspace, "ls-files", "--cached", "--others", "--exclude-standard", "-z").split("\0"):
        if not name:continue
        try:path_for(workspace, name)
        except (ValueError, OSError):continue
        result.append(name)
    return result[:1000]


def checks(workspace):
    result = []
    for name in changed(workspace):
        path = path_for(workspace, name)
        if path.suffix == ".py":
            try:ast.parse(path.read_text(encoding="utf-8-sig"));result.append({"path": name, "ok": True, "kind": "python_syntax"})
            except (SyntaxError, UnicodeError) as exc:result.append({"path": name, "ok": False, "kind": "python_syntax", "line": getattr(exc, "lineno", None)})
        elif path.suffix in {".js", ".cjs", ".mjs"}:
            from .antigravity_cli_brain import environment
            proc = subprocess.run(["node", "--check", str(path)], cwd=workspace, env=environment(), capture_output=True, timeout=15,
                **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
            result.append({"path": name, "ok": proc.returncode == 0, "kind": "javascript_syntax"})
    try:git(workspace, "diff", "--no-ext-diff", "--check");result.append({"kind": "diff_whitespace", "ok": True})
    except ValueError:result.append({"kind": "diff_whitespace", "ok": False})
    return {"ok": all(x["ok"] for x in result), "static": result, "tests": "not_run", "host": "not_verified"}


def changed(workspace):
    tracked = git(workspace, "diff", "--name-only", "--no-ext-diff", "-z").split("\0")
    untracked = git(workspace, "ls-files", "--others", "--exclude-standard", "-z").split("\0")
    return sorted({x for x in tracked + untracked if x})


def toolbox(job, check):
    workspace = job["workspace"]
    read = set()
    count = 0
    schemas = {x["function"]["name"]: x["function"]["parameters"] for x in coding_agents.CATALOG}
    def invoke(name, arguments):
        nonlocal count
        check();count += 1
        if count > 64:raise ValueError("coding_tool_limit")
        try:
            from jsonschema import Draft202012Validator
            if name not in schemas or not Draft202012Validator(schemas[name]).is_valid(arguments):raise ValueError("invalid_tool_arguments")
            if name == "list_files":return {"files": files(workspace)}
            if name == "run_static_checks":return checks(workspace)
            path = path_for(workspace, arguments["path"])
            if name == "read_file":
                if path.stat().st_size > 256000:raise ValueError("file_too_large")
                content = path.read_bytes()
                read.add(path)
                result = {"content": content.decode("utf-8-sig"), "sha256": hashlib.sha256(content).hexdigest()}
            else:
                for ancestor in (path.parent, *path.parent.parents):
                    instruction = ancestor / "AGENTS.md"
                    if instruction.is_file() and instruction not in read:raise ValueError("read_applicable_AGENTS_first")
                    if ancestor == Path(workspace):break
                data = arguments["content"].encode("utf-8")
                if len(data) > 512000 or len(changed(workspace)) >= 20:raise ValueError("edit_limit")
                previous = path.read_bytes() if path.exists() else None
                actual = hashlib.sha256(previous).hexdigest() if previous is not None else ""
                if actual != arguments["expected_sha256"]:raise ValueError("file_changed_read_again")
                if previous and b"\r\n" in previous and b"\r\n" not in data:data = data.replace(b"\n", b"\r\n")
                path.parent.mkdir(parents=True, exist_ok=True)
                temp = path.with_name(path.name + ".petit-" + uuid4().hex)
                try:temp.write_bytes(data);check();os.replace(temp, path)
                finally:
                    if temp.exists():temp.unlink()
                result = {"saved": True, "sha256": hashlib.sha256(data).hexdigest()}
            event(job["id"], name, arguments.get("path", ""))
            return result
        except (ValueError, OSError, UnicodeError) as exc:
            event(job["id"], "tool_rejected", name)
            return {"error": str(exc) if isinstance(exc, ValueError) else type(exc).__name__}
    return invoke


def run_job(job_id):
    job = get(job_id)
    started = time.monotonic()
    def check():
        current = get(job_id)
        if _stop.is_set() or current["cancel_requested"]:raise InterruptedError("取消要求で停止しました。差分は保持しています。")
        if time.monotonic() - started > 900:raise ValueError("開発タスクの実行時間上限に達しました。")
        data = settings.load()
        if not brain_priority.permitted(job["provider"], data):raise ValueError("CLI接続が解除されました。")
        require_repository(job["repository"])
        if brain_priority.target(job["provider"]).get("model", "") != job["model"]:raise ValueError("CLIモデル設定が変更されました。")
    try:
        check()
        root = require_repository(job["repository"])
        if git(root, "rev-parse", "HEAD").strip() != job["base_commit"]:raise ValueError("承認後に開始コミットが変更されました。")
        storage = project_workspaces._safe_root(Path(config.STORAGE_DIR))
        workspace = storage / "coding-jobs" / job_id
        workspace.parent.mkdir(parents=True, exist_ok=True)
        project_workspaces._safe_root(workspace.parent)
        if workspace.exists():raise ValueError("既存作業場所は上書きしません。")
        # Clone committed files only. No user uncommitted work is copied or reset.
        git(root, "clone", "--no-local", "--no-hardlinks", "--no-checkout", "--", str(root), str(workspace))
        git(workspace, "remote", "remove", "origin")
        git(workspace, "checkout", "--detach", job["base_commit"])
        branch = "fix/petit-" + job_id[:12]
        git(workspace, "checkout", "-b", branch)
        with db.get_connection() as connection:
            connection.execute("UPDATE coding_jobs SET workspace=?,branch=? WHERE id=?", (str(workspace), branch, job_id))
        job = get(job_id)
        event(job_id, "workspace_ready", "開始コミットの専用コピーを作成しました。")
        summary = coding_agents.run(job["provider"], brain_priority.target(job["provider"]), job["goal"], toolbox(job, check), check,
            lambda kind: event(job_id, kind))
        check()
        validation = checks(workspace)
        finish(job_id, "ready_for_review" if validation["ok"] else "checks_failed", summary=summary, checks=validation)
    except InterruptedError as exc:finish(job_id, "cancelled", error=str(exc))
    except Exception as exc:
        # Never expose CLI raw diagnostics, secret URLs or traceback content.
        from .lmstudio_client import LMStudioError
        message = str(exc) if isinstance(exc, (ValueError, LMStudioError)) else "開発タスクが停止しました（" + type(exc).__name__ + "）。接続・権限を確認してください。"
        finish(job_id, "failed", error=message[:1000])


def pump():
    with db.get_connection() as connection:
        row = connection.execute("SELECT id FROM coding_jobs WHERE status='queued' AND cancel_requested=0 ORDER BY created_at LIMIT 1").fetchone()
        if not row:return False
        cursor = connection.execute("UPDATE coding_jobs SET status='running',updated_at=? WHERE id=? AND status='queued'", (db.now_iso(), row[0]))
        claimed = cursor.rowcount == 1
    if claimed:event(row[0], "running");run_job(row[0])
    return claimed


def start():
    global _worker
    ensure_schema()
    if _worker and _worker.is_alive():return
    with db.get_connection() as connection:
        connection.execute("UPDATE coding_jobs SET status='interrupted',error='Core再起動で中断しました。自動再実行していません。' WHERE status='running'")
    _stop.clear()
    def loop():
        while not _stop.wait(.5):
            try:pump()
            except Exception:continue
    _worker = threading.Thread(target=loop, name="petit-coding-jobs", daemon=True)
    _worker.start()


def stop():
    _stop.set()
    if _worker:_worker.join(timeout=15)
