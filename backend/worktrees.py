"""Agent worktrees in PETIT Home (H4, Concept §4 L1/L2).

L1 (no confirmation): create a ``petit/<slug>`` worktree of a registered repo inside
PETIT Home, edit it, run its tests, commit, and push that branch.
L2 (approval): open a pull request.
L3 (never): push to the default branch / main / master, force-push, push other branches.

Core runs git and test commands itself, so the CLI never holds git credentials, and
repository hooks are disabled for every git call.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from . import coding_jobs, db, petit_home

BRANCH_PREFIX = "petit/"
PROTECTED_BRANCHES = {"main", "master", "develop", "trunk", "production", "release"}
TEST_TIMEOUT = 600
OUTPUT_LIMIT = 20000
PYTHON_MODULES = {"pytest", "unittest", "mypy", "ruff", "compileall", "black", "flake8", "pyflakes"}
SCRIPT_RUNNERS = {"npm", "pnpm", "yarn", "bun"}
NPX_TOOLS = {"eslint", "tsc", "vitest", "jest", "prettier", "playwright", "biome"}
DIRECT_RUNNERS = {"pytest", "ruff", "mypy", "go", "cargo", "make", "tox", "node", "deno", "swift", "dotnet", "gradle",
                  "./gradlew", "mvn"}
GO_CARGO_SUBCOMMANDS = {"test", "vet", "build", "check", "clippy", "fmt"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS petit_worktrees (
    id TEXT PRIMARY KEY, repository TEXT NOT NULL, path TEXT NOT NULL UNIQUE, branch TEXT NOT NULL,
    base_ref TEXT NOT NULL, base_commit TEXT NOT NULL, status TEXT NOT NULL, pushed_commit TEXT, pr_url TEXT,
    created_at REAL NOT NULL, updated_at REAL NOT NULL
);
"""


class WorktreeError(ValueError):
    pass


def ensure_schema() -> None:
    with db.get_connection() as connection:
        connection.executescript(SCHEMA)


def _env(*, network: bool = False) -> dict:
    from .antigravity_cli_brain import environment
    env = environment()
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"})
    if network:
        # Push uses the user's own git credentials on this PC; nothing is handed to the CLI.
        for key in ("SSH_AUTH_SOCK", "GIT_SSH_COMMAND", "XDG_CONFIG_HOME", "GIT_CONFIG_GLOBAL"):
            if os.environ.get(key):
                env[key] = os.environ[key]
    return env


def _git(root: Path, *args: str, network: bool = False, timeout: int = 60) -> str:
    result = subprocess.run(["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-C", str(root), *args],
                            capture_output=True, timeout=timeout, env=_env(network=network),
                            **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
    if result.returncode:
        detail = result.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or [""]
        raise WorktreeError("Git操作に失敗しました: " + detail[0][:200])
    return result.stdout.decode("utf-8", "replace")


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40].strip("-")
    return slug or "task"


def _default_ref(repo: Path) -> tuple[str, str]:
    """(ref to branch from, default branch name). Prefers origin's HEAD."""
    try:
        ref = _git(repo, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD").strip()
        return ref, ref.rsplit("/", 1)[-1]
    except WorktreeError:
        branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
        return "HEAD", branch


def _row(worktree_id: str) -> dict:
    ensure_schema()
    with db.get_connection() as connection:
        row = connection.execute("SELECT * FROM petit_worktrees WHERE id=?", (worktree_id,)).fetchone()
    if row is None:
        raise WorktreeError("worktree が見つかりません。open_worktree で作成してください。")
    item = dict(row)
    if item["status"] != "open":
        raise WorktreeError("この worktree は閉じています。")
    path = Path(item["path"])
    if not path.is_dir() or path.is_symlink():
        raise WorktreeError("worktree のフォルダが見つかりません。")
    return item


def _public(item: dict) -> dict:
    home = petit_home.root()
    path = Path(item["path"])
    try:
        relative = path.relative_to(home).as_posix()
    except ValueError:
        relative = str(path)
    return {"worktree_id": item["id"], "repository": Path(item["repository"]).name, "branch": item["branch"],
            "path": relative, "base": item["base_ref"], "pushed_commit": item.get("pushed_commit"), "pr_url": item.get("pr_url")}


def open_worktree(repository: str, task: str) -> dict:
    ensure_schema()
    repo = coding_jobs.require_repository(repository)
    coding_jobs.validate_repository(repo)
    try:
        _git(repo, "fetch", "--quiet", "origin", network=True, timeout=120)  # best effort, read-only
    except (WorktreeError, subprocess.SubprocessError):
        pass
    base_ref, default = _default_ref(repo)
    base_commit = _git(repo, "rev-parse", base_ref).strip()
    worktree_id = uuid4().hex[:12]
    branch = f"{BRANCH_PREFIX}{_slug(task)}-{worktree_id[:6]}"
    home = petit_home.ensure()
    path = home / "worktrees" / f"{repo.name}-{worktree_id[:6]}"
    path.parent.mkdir(exist_ok=True)
    _git(repo, "worktree", "add", "-b", branch, str(path), base_commit)
    now = time.time()
    with db.get_connection() as connection:
        connection.execute("INSERT INTO petit_worktrees VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                           (worktree_id, str(repo), str(path), branch, default, base_commit, "open", None, None, now, now))
    return {**_public(_row(worktree_id)), "created": True,
            "note": "このフォルダの中で編集し、run_worktree_check でテスト、commit_worktree で commit、push_worktree で push する。"}


def status(worktree_id: str) -> dict:
    item = _row(worktree_id)
    path = Path(item["path"])
    return {**_public(item),
            "changes": _git(path, "status", "--porcelain")[:OUTPUT_LIMIT],
            "commits": _git(path, "log", "--oneline", f"{item['base_commit']}..HEAD")[:OUTPUT_LIMIT],
            "diff_stat": _git(path, "diff", "--stat", item["base_commit"])[:OUTPUT_LIMIT]}


def validate_check_command(argv: list[str]) -> list[str]:
    if not argv or not all(isinstance(x, str) and x and "\0" not in x for x in argv) or len(argv) > 40:
        raise WorktreeError("command は空でない文字列の配列で渡してください。")
    head = argv[0]
    name = Path(head).name
    if name in {"python", "python3", "py"}:
        if len(argv) >= 3 and argv[1] == "-m" and argv[2] in PYTHON_MODULES:
            return argv
        raise WorktreeError("python は -m pytest / unittest / mypy / ruff などのテスト・検査だけ実行できます。")
    if name in SCRIPT_RUNNERS:
        if len(argv) >= 2 and argv[1] in {"test", "run", "exec"} and not (argv[1] == "run" and len(argv) < 3):
            return argv
        raise WorktreeError("npm / pnpm / yarn は test か run <script> だけ実行できます。")
    if name == "npx":
        if len(argv) >= 2 and argv[1] in NPX_TOOLS:
            return argv
        raise WorktreeError("npx は eslint / tsc / vitest / jest などの検査ツールだけ実行できます。")
    if name in {"go", "cargo"}:
        if len(argv) >= 2 and argv[1] in GO_CARGO_SUBCOMMANDS:
            return argv
        raise WorktreeError("go / cargo は test / vet / build / check などだけ実行できます。")
    if head in DIRECT_RUNNERS or name in DIRECT_RUNNERS:
        if "/" in head and head != "./gradlew":
            raise WorktreeError("実行ファイルはパスではなく名前で指定してください。")
        return argv
    raise WorktreeError("テスト・ビルド・静的検査のコマンドだけ実行できます（pytest / npm test / go test など）。")


def run_check(worktree_id: str, command: list[str]) -> dict:
    """L1: run a test/build/lint command in the worktree. No shell; no Core secrets."""
    item = _row(worktree_id)
    argv = validate_check_command(command)
    if argv[0] == "./gradlew":
        wrapper = Path(item["path"]) / "gradlew"
        executable = str(wrapper) if wrapper.is_file() and not wrapper.is_symlink() else None
    else:
        executable = shutil.which(argv[0], path=_env().get("PATH"))
    if not executable:
        raise WorktreeError(f"{argv[0]} が見つかりません。")
    started = time.monotonic()
    try:
        proc = subprocess.run([executable, *argv[1:]], cwd=item["path"], env=_env(), capture_output=True,
                              timeout=TEST_TIMEOUT, **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
        code, out, err, timed_out = proc.returncode, proc.stdout, proc.stderr, False
    except subprocess.TimeoutExpired as exc:
        code, out, err, timed_out = None, exc.stdout or b"", exc.stderr or b"", True
    text = (out + b"\n" + err).decode("utf-8", "replace")
    return {"worktree_id": worktree_id, "command": argv, "exit_code": code, "passed": code == 0, "timed_out": timed_out,
            "seconds": round(time.monotonic() - started, 2),
            # Tail keeps the summary line most runners print last.
            "output": text[-OUTPUT_LIMIT:]}


def commit(worktree_id: str, message: str) -> dict:
    item = _row(worktree_id)
    path = Path(item["path"])
    message = message.strip()
    if not message:
        raise WorktreeError("commit メッセージを入れてください。")
    if not _git(path, "status", "--porcelain").strip():
        return {"committed": False, "reason": "変更がありません。"}
    _git(path, "add", "-A")
    _git(path, "-c", "user.name=PETIT", "-c", "user.email=petit@localhost", "commit", "-q", "-m", message[:2000])
    return {"committed": True, "commit": _git(path, "rev-parse", "HEAD").strip(), **_public(item)}


def _check_push_target(item: dict) -> str:
    branch = item["branch"]
    leaf = branch.rsplit("/", 1)[-1]
    if not branch.startswith(BRANCH_PREFIX) or branch == item["base_ref"] or leaf in PROTECTED_BRANCHES \
            or branch.removeprefix(BRANCH_PREFIX) in PROTECTED_BRANCHES:
        raise WorktreeError("PETIT が push できるのは自分で作った petit/ ブランチだけです（L3）。")
    current = _git(Path(item["path"]), "rev-parse", "--abbrev-ref", "HEAD").strip()
    if current != branch:
        raise WorktreeError("worktree のブランチが作成時と違います。push しません。")
    return branch


def push(worktree_id: str, commit: str) -> dict:
    """L1: push the worktree's own petit/ branch. Never the default branch, never --force."""
    item = _row(worktree_id)
    branch = _check_push_target(item)
    path = Path(item["path"])
    head = _git(path, "rev-parse", "HEAD").strip()
    if not commit or not head.startswith(commit.strip().lower()) or len(commit.strip()) < 7:
        raise WorktreeError("push する commit が現在の HEAD と一致しません。commit_worktree の結果の commit を渡してください。")
    if head == item["base_commit"]:
        return {"pushed": False, "reason": "commit がありません。先に commit_worktree してください。"}
    _git(path, "push", "--porcelain", "origin", f"HEAD:refs/heads/{branch}", network=True, timeout=180)
    with db.get_connection() as connection:
        connection.execute("UPDATE petit_worktrees SET pushed_commit=?, updated_at=? WHERE id=?", (head, time.time(), worktree_id))
    return {"pushed": True, "branch": branch, "commit": head, **_public(_row(worktree_id))}


def pull_request_preview(arguments: dict) -> str:
    item = _row(str(arguments.get("worktree_id") or ""))
    path = Path(item["path"])
    commits = _git(path, "log", "--oneline", f"{item['base_commit']}..HEAD").strip() or "（commit なし）"
    stat = _git(path, "diff", "--stat", item["base_commit"], "HEAD").strip() or "（差分なし）"
    pushed = "push 済み" if item.get("pushed_commit") == _git(path, "rev-parse", "HEAD").strip() else "未 push（先に push_worktree）"
    return (f"リポジトリ: {Path(item['repository']).name}\n{item['branch']} → {item['base_ref']}（{pushed}）\n"
            f"タイトル: {arguments.get('title', '')}\n\n本文:\n{arguments.get('body', '')}\n\ncommit:\n{commits}\n\n差分:\n{stat}")


def create_pull_request(worktree_id: str, title: str, body: str) -> dict:
    """L2 (approved): open a PR with the user's own gh login on this PC."""
    item = _row(worktree_id)
    branch = _check_push_target(item)
    path = Path(item["path"])
    if item.get("pushed_commit") != _git(path, "rev-parse", "HEAD").strip():
        raise WorktreeError("最新の commit が push されていません。先に push_worktree してください。")
    gh = shutil.which("gh")
    if not gh:
        raise WorktreeError("GitHub CLI（gh）が見つかりません。PC で gh をインストールしてログインしてください。")
    env = _env(network=True)
    for key in ("GH_CONFIG_DIR",):
        if os.environ.get(key):
            env[key] = os.environ[key]
    proc = subprocess.run([gh, "pr", "create", "--head", branch, "--base", item["base_ref"], "--title", title[:250],
                           "--body", body[:60000]], cwd=path, env=env, capture_output=True, timeout=120)
    if proc.returncode:
        raise WorktreeError("PR を作成できませんでした: " + proc.stderr.decode("utf-8", "replace").strip()[-200:])
    url = proc.stdout.decode().strip().splitlines()[-1] if proc.stdout.strip() else ""
    with db.get_connection() as connection:
        connection.execute("UPDATE petit_worktrees SET pr_url=?, updated_at=? WHERE id=?", (url, time.time(), worktree_id))
    return {"created": True, "url": url, **_public(_row(worktree_id))}


def close(worktree_id: str) -> dict:
    item = _row(worktree_id)
    _git(Path(item["repository"]), "worktree", "remove", "--force", item["path"])
    with db.get_connection() as connection:
        connection.execute("UPDATE petit_worktrees SET status='closed', updated_at=? WHERE id=?", (time.time(), worktree_id))
    return {"closed": True, "branch_kept": item["branch"], "worktree_id": worktree_id}


def list_open() -> list[dict]:
    ensure_schema()
    with db.get_connection() as connection:
        rows = connection.execute("SELECT * FROM petit_worktrees WHERE status='open' ORDER BY created_at DESC LIMIT 30").fetchall()
    return [_public(dict(r)) for r in rows]
