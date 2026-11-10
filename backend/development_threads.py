"""Repository-scoped Develop threads using the existing conversation and coding job stores.

A Develop thread owns metadata only: job goals, summaries and events remain in the
coding_jobs tables. Legacy/unbound jobs are not silently assigned to a thread.
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from . import coding_jobs, conversation_store, db

SCHEMA = """
CREATE TABLE IF NOT EXISTS coding_develop_threads (
    thread_id TEXT PRIMARY KEY REFERENCES threads(id),
    repository TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_coding_develop_repo ON coding_develop_threads(repository);
"""


def ensure_schema():
    conversation_store.ensure_schema()
    coding_jobs.ensure_schema()
    with db.get_connection() as connection:
        connection.executescript(SCHEMA)


def _repository(path):
    if not path:
        return ""
    return str(coding_jobs.require_repository(path))


def _row(thread_id):
    with db.get_connection() as connection:
        row = connection.execute(
            "SELECT d.thread_id,d.repository,d.created_at,t.title FROM coding_develop_threads d "
            "JOIN threads t ON t.id=d.thread_id WHERE d.thread_id=?", (thread_id,)
        ).fetchone()
    if not row:
        raise ValueError("開発スレッドが見つかりません。")
    return dict(row)


def create(repository="", title="", thread_id=None):
    """Idempotent for a supplied thread ID; cannot hijack a non-Develop thread."""
    ensure_schema()
    repository = _repository(repository)
    thread_id = thread_id or uuid4().hex
    owner = conversation_store.create_thread(thread_id, source="develop", title=title[:160])
    if owner["source"] != "develop":
        raise ValueError("既存の通常会話を開発スレッドとして使用できません。")
    with db.get_connection() as connection:
        current = connection.execute(
            "SELECT repository FROM coding_develop_threads WHERE thread_id=?", (thread_id,)
        ).fetchone()
        if current and current["repository"] != repository:
            raise ValueError("同じスレッドIDで異なるリポジトリを指定できません。")
        connection.execute(
            "INSERT OR IGNORE INTO coding_develop_threads(thread_id,repository,created_at) VALUES(?,?,?)",
            (thread_id, repository, db.now_iso())
        )
    return _row(thread_id)


def verify(thread_id, repository):
    ensure_schema()
    owner = _row(thread_id)
    if owner["repository"] != _repository(repository):
        raise ValueError("スレッドの対象リポジトリと開発依頼が一致しません。")
    return owner


def attach_repository(thread_id, repository):
    """Bind a repository-less thread once, preserving its existing jobs."""
    ensure_schema()
    repository = _repository(repository)
    if not repository:
        raise ValueError("登録済みの対象フォルダを選択してください。")
    with db.write_transaction() as connection:
        row = connection.execute(
            "SELECT repository FROM coding_develop_threads WHERE thread_id=?", (thread_id,)
        ).fetchone()
        if row is None:
            raise ValueError("開発スレッドが見つかりません。")
        if row["repository"] and row["repository"] != repository:
            raise ValueError("別のリポジトリへスレッドを移動できません。")
        connection.execute(
            "UPDATE coding_develop_threads SET repository=? WHERE thread_id=?",
            (repository, thread_id)
        )
    return _row(thread_id)


def _latest(connection, thread_id):
    row = connection.execute(
        "SELECT j.id,j.goal,j.summary,j.error,j.provider,j.status,j.updated_at,j.created_at "
        "FROM coding_jobs j JOIN coding_job_routes r ON r.job_id=j.id "
        "WHERE r.thread_id=? ORDER BY j.created_at DESC,j.id DESC LIMIT 1",
        (thread_id,)
    ).fetchone()
    if not row:
        return None
    job = dict(row)
    job["latest_message"] = (job["summary"] or job["error"] or job["goal"])[:300]
    return job


def list_threads(repository=None, limit=100):
    ensure_schema()
    limit = max(1, min(int(limit), 200))
    query = (
        "SELECT d.thread_id,d.repository,d.created_at,t.title FROM coding_develop_threads d "
        "JOIN threads t ON t.id=d.thread_id"
    )
    params = []
    if repository is not None:
        query += " WHERE d.repository=?"
        params.append(_repository(repository))
    query += " ORDER BY d.created_at DESC LIMIT ?"
    params.append(limit)
    with db.get_connection() as connection:
        rows = [dict(r) for r in connection.execute(query, params)]
        for row in rows:
            row["latest_job"] = _latest(connection, row["thread_id"])
    return sorted(rows, key=lambda row: (
        (row["latest_job"] or {}).get("updated_at") or row["created_at"], row["created_at"]
    ), reverse=True)


def detail(thread_id):
    ensure_schema()
    owner = _row(thread_id)
    owner["jobs"] = list(reversed(coding_jobs.list_jobs(thread_id)))
    return owner


def repositories():
    """Observed local Git HEAD plus last coding result, not an AI-invented status."""
    ensure_schema()
    roots = coding_jobs.roots()
    with db.get_connection() as connection:
        for root in roots:
            path = root["path"]
            root["branch"] = None
            root["changed"] = None
            if root["mode"] == "git" and not root.get("error"):
                try:
                    root["branch"] = coding_jobs.git(path, "branch", "--show-current").strip() or "(detached)"
                    changed = coding_jobs.git(path, "status", "--porcelain", "--untracked-files=no")
                    root["changed"] = len([line for line in changed.splitlines() if line])
                except (ValueError, OSError):
                    root["error"] = "Gitの最新状態を取得できません。"
            row = connection.execute(
                "SELECT j.id,j.goal,j.summary,j.status,j.updated_at FROM coding_jobs j "
                "WHERE j.repository=? ORDER BY j.updated_at DESC,j.id DESC LIMIT 1", (path,)
            ).fetchone()
            root["latest_job"] = dict(row) if row else None
            root["thread_count"] = connection.execute(
                "SELECT COUNT(*) FROM coding_develop_threads WHERE repository=?", (path,)
            ).fetchone()[0]
            root["observed_at"] = db.now_iso()
    return roots
