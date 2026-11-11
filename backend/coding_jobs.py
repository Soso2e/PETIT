"""Durable, approved CLI coding jobs over isolated local repository copies."""
from __future__ import annotations

import ast
from contextlib import closing
import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import threading
import time
from uuid import uuid4

from . import (config, db, setup_store as settings, project_workspaces, brain_priority, coding_agents,
               development_models, development_pc, development_roots)

log = logging.getLogger(__name__)

_lock = threading.RLock()
_stop = threading.Event()
_worker = None
TERMINAL = {"completed", "failed", "cancelled", "interrupted", "ready_for_review", "checks_failed"}
_is_reserved = getattr(os.path, "isreserved", lambda value: Path(value).is_reserved())
SCHEMA = """
CREATE TABLE IF NOT EXISTS coding_jobs (
 id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, input_hash TEXT NOT NULL, task_id INTEGER,
 project_id TEXT, repository TEXT NOT NULL, base_commit TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
 goal TEXT NOT NULL, status TEXT NOT NULL, workspace TEXT, branch TEXT, summary TEXT NOT NULL DEFAULT '',
 checks_json TEXT NOT NULL DEFAULT '{}', error TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS coding_job_events (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, kind TEXT NOT NULL,
 detail TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS coding_job_routes (
 job_id TEXT PRIMARY KEY REFERENCES coding_jobs(id), thread_id TEXT, turn_id TEXT,
 mode TEXT NOT NULL, selection_json TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS coding_job_routes_turn ON coding_job_routes(turn_id) WHERE turn_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS coding_job_routes_thread ON coding_job_routes(thread_id);
"""


def _migrate_task_id_nullable(connection):
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='coding_jobs'").fetchone():
        return
    info = connection.execute("PRAGMA table_info(coding_jobs)").fetchall()
    task_id_info = [col for col in info if col[1] == "task_id"]
    if task_id_info and task_id_info[0][3] == 1:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("""
        CREATE TABLE coding_jobs_temp (
         id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, input_hash TEXT NOT NULL, task_id INTEGER,
         project_id TEXT, repository TEXT NOT NULL, base_commit TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
         goal TEXT NOT NULL, status TEXT NOT NULL, workspace TEXT, branch TEXT, summary TEXT NOT NULL DEFAULT '',
         checks_json TEXT NOT NULL DEFAULT '{}', error TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0,
         created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )
        """)
        connection.execute("""
        INSERT INTO coding_jobs_temp SELECT id, request_id, input_hash, task_id, project_id, repository, base_commit, provider, model, goal, status, workspace, branch, summary, checks_json, error, cancel_requested, created_at, updated_at FROM coding_jobs
        """)
        connection.execute("DROP TABLE coding_jobs")
        connection.execute("ALTER TABLE coding_jobs_temp RENAME TO coding_jobs")
        connection.execute("PRAGMA foreign_keys = ON")


def ensure_schema():
    with _lock, db.get_connection() as connection:
        if connection.execute("SELECT 1 FROM sqlite_master WHERE name='coding_pc_actions'").fetchone():
            _migrate_task_id_nullable(connection)
            return
        if connection.execute("SELECT 1 FROM sqlite_master WHERE name='coding_jobs'").fetchone():
            connection.executescript(SCHEMA + development_pc.ACTION_SCHEMA)
            _migrate_task_id_nullable(connection)
            return
        if db._transaction.get() is not None:
            raise ValueError("開発タスク画面を開いて初期化してください。")
        backup = Path(str(config.DB_PATH) + ".before-coding-jobs.bak")
        if not backup.exists():
            with closing(sqlite3.connect(backup)) as destination:
                connection.backup(destination)
                if destination.execute("PRAGMA quick_check").fetchone()[0] != "ok":raise ValueError("backup_check_failed")
        connection.executescript(SCHEMA + development_pc.ACTION_SCHEMA)
        _migrate_task_id_nullable(connection)


def git(root, *args):
    from .antigravity_cli_brain import environment
    env = {**environment(), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0"}
    result = subprocess.run(["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-C", str(root), *args],
        capture_output=True, timeout=45, env=env, **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
    if result.returncode:raise ValueError("Git操作に失敗しました。リポジトリと開始コミットを確認してください。")
    return result.stdout.decode("utf-8", "replace")


def validate_repository(path):
    root = project_workspaces._safe_root(Path(path))
    if root == root.parent or "_private" in {p.casefold() for p in root.parts}:raise ValueError("invalid_repository")
    if Path(git(root, "rev-parse", "--show-toplevel").strip()).resolve() != root:raise ValueError("Gitルートを指定してください。")
    return root


def roots():
    result = []
    for path, source in development_roots.configured():
        entry = {"path": path, "name": Path(path).name, "source": source, "mode": "folder"}
        try:
            root = project_workspaces._safe_root(Path(path))
            entry.update(path=str(root), name=root.name)
            if is_git_root(root):
                entry.update(mode="git", head=git(root, "rev-parse", "HEAD").strip())
        except (ValueError, OSError, subprocess.SubprocessError):
            entry["error"] = "フォルダまたは開始コミットを参照できません。"
        result.append(entry)
    return result


def is_git_root(root):
    return (root / ".git").exists() and validate_repository(root) == root


def require_repository(path):
    raw = str(path or "").strip()
    for configured, _ in development_roots.configured():
        if raw == Path(configured).name or os.path.normcase(raw) == os.path.normcase(configured):
            path = configured
            break
    root = project_workspaces._safe_root(Path(path))
    allowed = []
    for configured, _ in development_roots.configured():
        try:allowed.append(os.path.normcase(str(project_workspaces._safe_root(Path(configured)))))
        except (ValueError, OSError):continue
    if os.path.normcase(str(root)) not in allowed:raise ValueError("開発用に登録されたフォルダを指定してください。")
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
        route = connection.execute("SELECT * FROM coding_job_routes WHERE job_id=?", (job_id,)).fetchone()
        if route:
            result.update(mode=route["mode"], selection=json.loads(route["selection_json"]))
            if route["mode"] == "pc":
                result["actions"] = development_pc.actions(connection, job_id)
    result["tests"] = result["checks"].get("tests", "not_run")
    result["host_acceptance"] = "not_verified"
    return result


def activity_summary(limit=30):
    """Read-only status projection for Activity without exposing goals or paths.

    Do not initialize the coding schema when merely opening the dashboard;
    showing an uninitialized state must not create a DB backup.
    """
    limit = max(1, min(int(limit), 100))
    with db.get_connection() as connection:
        if not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='coding_jobs'"
        ).fetchone():
            return {"initialized": False, "jobs": []}
        rows = connection.execute(
            "SELECT id, task_id, project_id, provider, status, "
            "created_at, updated_at FROM coding_jobs ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return {"initialized": True, "jobs": [dict(row) for row in rows]}


def list_jobs(thread_id=None):
    ensure_schema()
    with db.get_connection() as connection:
        if thread_id is None:
            ids = [r[0] for r in connection.execute("SELECT id FROM coding_jobs ORDER BY created_at DESC LIMIT 50")]
        else:
            ids = [r[0] for r in connection.execute(
                "SELECT job_id FROM coding_job_routes WHERE thread_id=? ORDER BY rowid DESC LIMIT 50", (thread_id,))]
    return [get(x) for x in ids]


def create(request_id, repository, goal, provider, *, approved=False, task_id=None, project_id=None, base_commit=None, thread_id=None, turn_id=None):
    ensure_schema()
    if provider not in {"codex", "antigravity_cli", "claude_code"}:raise ValueError("開発用CLIを選択してください。")
    if not goal.strip() or len(goal) > 8000:raise ValueError("開発目的を1〜8000文字で指定してください。")
    root = validate_repository(require_repository(repository))
    payload = json.dumps([str(root), goal, provider, task_id, project_id, base_commit, thread_id, turn_id], ensure_ascii=False)
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
        connection.execute("INSERT INTO coding_jobs(id,request_id,input_hash,task_id,project_id,repository,base_commit,provider,model,goal,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (job_id, request_id, digest, task_id, project_id, str(root), head, provider,
             brain_priority.target(provider).get("model") or "", goal, "queued" if approved else "proposed", now, now))
        if thread_id:
            connection.execute("INSERT INTO coding_job_routes VALUES(?,?,?,?,?)",
                               (job_id, thread_id, turn_id, "git", json.dumps({"provider": provider, "direct": approved}, ensure_ascii=False)))
    event(job_id, "queued" if approved else "proposed", "元checkoutの未コミット変更を含めず、HEADの専用コピーで作業します。")
    if thread_id:
        from . import development_threads
        try:
            development_threads.register_conversation_thread(thread_id, str(root), title=goal[:120])
        except Exception as exc:
            log.warning("Failed to register develop thread for thread_id=%s: %s", thread_id, exc)
    return {"job_id": job_id, "task_id": task_id, "created": True, "started": approved, "status": "queued" if approved else "proposed"}


def create_development(request_id, repository, goal, model_key="auto", effort="medium", lightweight=False,
                       *, direct=False, thread_id=None, turn_id=None):
    ensure_schema()
    goal = goal.strip()
    if not goal or len(goal) > 8000:
        raise ValueError("開発目的を1〜8000文字で指定してください。")
    request_id = "develop:" + request_id
    digest = hashlib.sha256(json.dumps(
        [repository, goal, model_key, effort, lightweight, direct, thread_id, turn_id], ensure_ascii=False
    ).encode()).hexdigest()

    def previous(connection):
        row = connection.execute("SELECT id,input_hash FROM coding_jobs WHERE request_id=?", (request_id,)).fetchone()
        if row and row["input_hash"] != digest:
            raise ValueError("同じ依頼IDに異なる入力は指定できません。")
        return row["id"] if row else None

    with db.get_connection() as connection:
        existing = previous(connection)
    if existing:
        return get(existing)
    root = require_repository(repository) if repository else None
    mode = "git" if root and is_git_root(root) else "pc"
    if root and mode == "pc":
        development_pc.host_path(str(root), directory=True)
    head = git(root, "rev-parse", "HEAD").strip() if mode == "git" else ""
    provider, model, selection = development_models.select(model_key, effort, lightweight)
    job_id, now = uuid4().hex, db.now_iso()
    status = "queued" if direct else "proposed"
    with db.write_transaction() as connection:
        existing = previous(connection)
        if existing:
            return get(existing)
        connection.execute(
            "INSERT INTO coding_jobs(id,request_id,input_hash,task_id,repository,base_commit,provider,model,goal,status,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (job_id, request_id, digest, None, str(root) if root else "", head, provider, model, goal, status, now, now))
        connection.execute("INSERT INTO coding_job_routes VALUES(?,?,?,?,?)",
                           (job_id, thread_id, turn_id, mode, json.dumps(selection, ensure_ascii=False)))
        event(job_id, status)
    if thread_id:
        from . import development_threads
        try:
            development_threads.register_conversation_thread(thread_id, str(root) if root else (repository or ""), title=goal[:120])
        except Exception as exc:
            log.warning("Failed to register develop thread for thread_id=%s: %s", thread_id, exc)
    return get(job_id)


def turn_job(request_id):
    with db.get_connection() as connection:
        if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='coding_job_routes'").fetchone():
            return None
        row = connection.execute("SELECT job_id FROM coding_job_routes WHERE turn_id=?", (request_id,)).fetchone()
    return row[0] if row else None


def approve(job_id):
    job = get(job_id)
    if job["status"] != "proposed":
        return job
    root = require_repository(job["repository"]) if job["repository"] else None
    if job.get("mode") != "pc" and git(root, "rev-parse", "HEAD").strip() != job["base_commit"]:
        raise ValueError("開始コミットが変わりました。新しい依頼で確認してください。")
    with db.get_connection() as connection:
        connection.execute("UPDATE coding_jobs SET status='queued',updated_at=? WHERE id=? AND status='proposed' AND cancel_requested=0", (db.now_iso(), job_id))
    return get(job_id)


def cancel(job_id):
    get(job_id)
    with db.write_transaction() as connection:
        connection.execute("UPDATE coding_jobs SET cancel_requested=1,status=CASE WHEN status IN ('proposed','queued','waiting_approval') THEN 'cancelled' ELSE status END,updated_at=? WHERE id=?", (db.now_iso(), job_id))
        connection.execute("UPDATE coding_pc_actions SET status='rejected' WHERE job_id=? AND status='proposed'", (job_id,))
    return {"job_id": job_id, "cancel_requested": True}


def finish(job_id, status, *, summary="", checks=None, error=None):
    with db.write_transaction() as connection:
        if status in {"ready_for_review", "checks_failed", "waiting_approval"}:
            row = connection.execute("SELECT cancel_requested FROM coding_jobs WHERE id=?", (job_id,)).fetchone()
            if row and row[0]:status = "cancelled"
        connection.execute("UPDATE coding_jobs SET status=?,summary=?,checks_json=?,error=?,updated_at=? WHERE id=?",
            (status, summary[:12000], json.dumps(checks or {}, ensure_ascii=False), error, db.now_iso(), job_id))
        if status in {"failed", "cancelled", "interrupted"}:
            connection.execute("UPDATE coding_pc_actions SET status='rejected' WHERE job_id=? AND status='proposed'", (job_id,))
        event(job_id, status)


def path_for(workspace, name):
    relative = Path(name)
    if relative.is_absolute() or relative.drive or not relative.parts or ".." in relative.parts or ":" in str(relative):raise ValueError("invalid_relative_path")
    denied = {".git", "_private", ".venv", "node_modules", "storage", ".ssh", ".gemini", ".codex"}
    if any(x.casefold().rstrip(" .") in denied or x.endswith((".", " ")) or "~" in x
           or (os.name == "nt" and _is_reserved(x)) for x in relative.parts):
        raise ValueError("protected_path")
    if any(x.casefold().startswith(".env") and x.casefold() not in {".env.example", ".env.sample", ".env.template", ".env.dist"} for x in relative.parts):
        raise ValueError("credential_path")
    root = Path(workspace).resolve(strict=True)
    path = root / relative
    for item in (path, *path.parents):
        if item == root:break
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("linked_path")
        if item == path and stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise ValueError("linked_path")
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


def checks(workspace, base="HEAD"):
    result = []
    for name in changed(workspace, base):
        path = path_for(workspace, name)
        if not path.exists():
            continue
        if path.suffix == ".py":
            try:ast.parse(path.read_text(encoding="utf-8-sig"));result.append({"path": name, "ok": True, "kind": "python_syntax"})
            except (SyntaxError, UnicodeError) as exc:result.append({"path": name, "ok": False, "kind": "python_syntax", "line": getattr(exc, "lineno", None)})
        elif path.suffix in {".js", ".cjs", ".mjs"}:
            from .antigravity_cli_brain import environment
            proc = subprocess.run(["node", "--check", str(path)], cwd=workspace, env=environment(), capture_output=True, timeout=15,
                **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
            result.append({"path": name, "ok": proc.returncode == 0, "kind": "javascript_syntax"})
    try:git(workspace, "-c", "core.whitespace=cr-at-eol", "diff", "--no-ext-diff", "--check", base);result.append({"kind": "diff_whitespace", "ok": True})
    except ValueError:result.append({"kind": "diff_whitespace", "ok": False})
    return {"ok": all(x["ok"] for x in result), "static": result, "tests": "not_run", "host": "not_verified"}


def changed(workspace, base="HEAD"):
    tracked = git(workspace, "diff", "--name-only", "--no-ext-diff", "-z", base).split("\0")
    untracked = git(workspace, "ls-files", "--others", "--exclude-standard", "-z").split("\0")
    return sorted({x for x in tracked + untracked if x})


def toolbox(job, check, catalog=None, check_results=None):
    workspace = job["workspace"]
    pc = job.get("mode") == "pc"
    root = job.get("repository") or None
    read = set()
    count = 0
    schemas = {x["function"]["name"]: x["function"]["parameters"] for x in (catalog or coding_agents.CATALOG)}

    def scratch_path(name):
        path = path_for(workspace, name)
        if pc and not development_pc.permitted_parts(path.relative_to(workspace).parts):
            raise ValueError("protected_path")
        return path

    def invoke(name, arguments):
        nonlocal count
        check();count += 1
        if count > 64:raise ValueError("coding_tool_limit")
        try:
            from jsonschema import Draft202012Validator
            if name not in schemas or not Draft202012Validator(schemas[name]).is_valid(arguments):raise ValueError("invalid_tool_arguments")
            if name == "search_pc_files":
                return development_pc.search(arguments["query"], root, check)
            if name == "read_pc_file":
                source = development_pc.host_path(arguments["path"], root)
                return {"content": development_pc.read_bytes(source, 256000).decode("utf-8-sig")}
            if name == "copy_pc_file_to_workspace":
                source = development_pc.host_path(arguments["path"], root)
                return development_pc.copy_to_scratch(source, scratch_path(arguments["destination"]))
            if name in coding_agents.PC_ACTIONS:
                return development_pc.propose(job, coding_agents.PC_ACTIONS[name], arguments, scratch_path)
            if name == "run_repository_check":
                from . import worktrees
                argv = worktrees.validate_job_check_command(arguments["argv"])
                result = worktrees.run_check_in(workspace, argv, check=check)
                check_results.append({key: value for key, value in result.items() if key != "output"})
                event(job["id"], "repository_check", "passed" if result["passed"] else "failed")
                return result
            if name == "commit_repository":
                from . import worktrees
                for name_to_commit in changed(workspace):
                    path_for(workspace, name_to_commit)
                return worktrees.commit_in(Path(workspace), arguments["message"], run_git=git)
            if name == "list_files":
                if pc:
                    from itertools import islice
                    return {"files": [str(path.relative_to(workspace)) for path in islice(Path(workspace).rglob("*"), 1000)
                                      if path.is_file()]}
                return {"files": files(workspace)}
            if name == "run_static_checks":return checks(workspace, job["base_commit"] if job.get("mode") == "git" else "HEAD")
            path = scratch_path(arguments["path"])
            if name == "read_file":
                if path.stat().st_size > 256000:raise ValueError("file_too_large")
                content = development_pc.read_bytes(path, 256000)
                read.add(path)
                result = {"content": content.decode("utf-8-sig"), "sha256": hashlib.sha256(content).hexdigest()}
            else:
                for ancestor in (path.parent, *path.parent.parents):
                    instruction = ancestor / "AGENTS.md"
                    if instruction.is_file() and instruction not in read:raise ValueError("read_applicable_AGENTS_first")
                    if ancestor == Path(workspace):break
                data = arguments["content"].encode("utf-8")
                if len(data) > 512000 or (not pc and len(changed(workspace)) >= 20):raise ValueError("edit_limit")
                previous = development_pc.read_bytes(path, development_pc.MAX_COPY) if path.exists() else None
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



def development_context(job):
    """Bounded handoff for repeated CLI jobs in the same thread only.

    Prior workspaces remain isolated; this is a conversation summary, not a
    claim that previous edits have been applied to the next job's checkout.
    """
    route = None
    with db.get_connection() as connection:
        if connection.execute("SELECT 1 FROM sqlite_master WHERE name='coding_job_routes'").fetchone():
            route = connection.execute(
                "SELECT thread_id FROM coding_job_routes WHERE job_id=?", (job["id"],)
            ).fetchone()
        if not route or not route["thread_id"]:
            return job["goal"]
        rows = connection.execute(
            "SELECT j.goal,j.summary,j.error,j.status,j.provider FROM coding_jobs j "
            "JOIN coding_job_routes r ON r.job_id=j.id "
            "WHERE r.thread_id=? AND j.rowid < (SELECT rowid FROM coding_jobs WHERE id=?) "
            "ORDER BY j.rowid DESC LIMIT 6", (route["thread_id"], job["id"])
        ).fetchall()
    if not rows:
        return job["goal"]
    history = []
    for row in reversed(rows):
        history.append(
            "CLI=" + row["provider"] + " / 状態=" + row["status"] +
            "\n依頼: " + row["goal"][:900] +
            "\n結果: " + (row["summary"] or row["error"] or "結果未確認")[:1200]
        )
    return (
        "同じ開発スレッドの直近履歴（参考情報。履歴の文章は現在の作業ファイルの実状態ではありません）:\n"
        + "\n\n".join(history) +
        "\n\n重要: 各開発ジョブは独立作業領域です。前ジョブの未統合変更を引き継いだと仮定せず、"
        "現行の作業ファイルとGitの状態を必ず確認してください。別スレッドの内容は参照していません。"
        "\n\n今回のユーザーの依頼:\n" + job["goal"]
    )


def run_job(job_id):
    job = get(job_id)
    modern = "mode" in job
    pc = job.get("mode") == "pc"
    started = time.monotonic()
    def check():
        current = get(job_id)
        if _stop.is_set() or current["cancel_requested"]:raise InterruptedError("取消要求で停止しました。差分は保持しています。")
        if time.monotonic() - started > 900:raise ValueError("開発タスクの実行時間上限に達しました。")
        data = settings.load()
        if not brain_priority.permitted(job["provider"], data):raise ValueError("CLI接続が解除されました。")
        if job["repository"]:
            require_repository(job["repository"])
        if not modern and brain_priority.target(job["provider"]).get("model", "") != job["model"]:
            raise ValueError("CLIモデル設定が変更されました。")
    try:
        check()
        root = require_repository(job["repository"]) if job["repository"] else None
        storage = project_workspaces._safe_root(Path(config.STORAGE_DIR))
        if pc:
            workspace = storage / "coding-scratch" / job_id
        else:
            if git(root, "rev-parse", "HEAD").strip() != job["base_commit"]:
                raise ValueError("開始コミットが変更されました。")
            workspace = storage / "coding-jobs" / job_id
        workspace.parent.mkdir(parents=True, exist_ok=True)
        project_workspaces._safe_root(workspace.parent)
        if workspace.exists():raise ValueError("既存作業場所は上書きしません。")
        # Clone committed files only. No user uncommitted work is copied or reset.
        branch = None
        if pc:
            workspace.mkdir()
        else:
            git(root, "clone", "--no-local", "--no-hardlinks", "--no-checkout", "--", str(root), str(workspace))
            git(workspace, "remote", "remove", "origin")
            git(workspace, "checkout", "--detach", job["base_commit"])
            branch = "fix/petit-" + job_id[:12]
            git(workspace, "checkout", "-b", branch)
        with db.get_connection() as connection:
            connection.execute("UPDATE coding_jobs SET workspace=?,branch=? WHERE id=?", (str(workspace), branch, job_id))
        job = get(job_id)
        event(job_id, "workspace_ready")
        target = brain_priority.target(job["provider"])
        if modern:
            target.update(model=job["model"], effort=job["selection"]["effort"])
        catalog = coding_agents.PC_CATALOG if pc else coding_agents.GIT_CATALOG if modern else coding_agents.CATALOG
        check_results = []
        instructions = coding_agents.PC_INSTRUCTIONS if pc else coding_agents.GIT_INSTRUCTIONS if modern else coding_agents.INSTRUCTIONS
        invoke = toolbox(job, check, catalog, check_results)
        args = (job["provider"], target, development_context(job) if modern else job["goal"], invoke, check, lambda kind: event(job_id, kind))
        if modern:
            summary = coding_agents.run(*args, catalog=catalog, instructions=instructions)
        else:
            summary = coding_agents.run(*args)
        check()
        validation = {"ok": True, "tests": "not_run"} if pc else checks(workspace, job["base_commit"]) if modern else checks(workspace)
        if check_results:
            validation["tests"] = "passed" if all(result["passed"] for result in check_results) else "failed"
            validation["commands"] = check_results
        pending = pc and any(action["status"] == "proposed" for action in get(job_id)["actions"])
        status = "waiting_approval" if pending else "ready_for_review" if validation["ok"] and validation["tests"] != "failed" else "checks_failed"
        finish(job_id, status, summary=summary, checks=validation)
    except InterruptedError as exc:finish(job_id, "cancelled", error=str(exc))
    except Exception as exc:
        # Never expose CLI raw diagnostics, secret URLs or traceback content.
        from .lmstudio_client import LMStudioError
        if job["provider"] == "claude_code" and getattr(exc, "reason", None) == "usage_limit":
            event(job_id, "usage_limit")
            development_models.invalidate()
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
        connection.execute("UPDATE coding_pc_actions SET status='unknown' WHERE status='running'")
        connection.execute("UPDATE coding_pc_actions SET status='rejected' WHERE status='proposed' AND job_id IN "
                           "(SELECT id FROM coding_jobs WHERE status='interrupted')")
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
