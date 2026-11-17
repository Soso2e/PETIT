"""Repository-scoped Develop threads using the existing conversation and coding job stores.

A Develop thread owns metadata only: job goals, summaries and events remain in the
coding_jobs tables. Legacy/unbound jobs are not silently assigned to a thread.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from . import coding_jobs, conversation_store, db

RETENTION_DAYS = 30
TRIAGE_STATUSES = ("active", "completed", "review_later")

SCHEMA = """
CREATE TABLE IF NOT EXISTS coding_develop_threads (
    thread_id TEXT PRIMARY KEY REFERENCES threads(id),
    repository TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    archived_at TEXT,
    triage_status TEXT NOT NULL DEFAULT 'active',
    deleted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_coding_develop_repo ON coding_develop_threads(repository);
"""


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def ensure_schema():
    conversation_store.ensure_schema()
    coding_jobs.ensure_schema()
    with db.get_connection() as connection:
        connection.executescript(SCHEMA)
        db._ensure_columns(
            connection,
            "coding_develop_threads",
            {
                "archived_at": "TEXT",
                "triage_status": "TEXT NOT NULL DEFAULT 'active'",
                "deleted_at": "TEXT",
            },
        )
    try:
        sync_chat_threads()
    except Exception:
        pass
    try:
        archive_stale_threads()
    except Exception:
        pass


def archive_stale_threads(retention_days: int = RETENTION_DAYS) -> int:
    """Hide Develop threads inactive for over retention_days while keeping job records."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(retention_days)))
    with db.get_connection() as connection:
        rows = connection.execute(
            "SELECT d.thread_id, d.created_at, j.status, j.updated_at "
            "FROM coding_develop_threads d "
            "LEFT JOIN coding_job_routes r ON r.thread_id=d.thread_id "
            "LEFT JOIN coding_jobs j ON j.id=r.job_id "
            "WHERE d.archived_at IS NULL AND d.deleted_at IS NULL"
        ).fetchall()
    if not rows:
        return 0
    threads: dict[str, dict] = {}
    for row in rows:
        tid = row["thread_id"]
        entry = threads.setdefault(tid, {"created_at": _parse_iso(row["created_at"]), "latest_job": None, "active": False})
        status = row["status"]
        if status is not None and status not in coding_jobs.TERMINAL:
            entry["active"] = True
        updated = _parse_iso(row["updated_at"])
        if updated and (entry["latest_job"] is None or updated > entry["latest_job"]):
            entry["latest_job"] = updated
    stale = []
    for tid, entry in threads.items():
        if entry["active"]:
            continue
        last_active = entry["latest_job"] or entry["created_at"]
        if last_active and last_active < cutoff:
            stale.append(tid)
    if not stale:
        return 0
    now = db.now_iso()
    with db.write_transaction() as connection:
        connection.executemany(
            "UPDATE coding_develop_threads SET archived_at=? WHERE thread_id=? AND archived_at IS NULL",
            [(now, tid) for tid in stale]
        )
    return len(stale)


def _repository(path):
    if not path:
        return ""
    return str(coding_jobs.require_repository(path))


def _row(thread_id):
    with db.get_connection() as connection:
        row = connection.execute(
            "SELECT d.thread_id,d.repository,d.created_at,d.archived_at,COALESCE(d.triage_status,'active') AS triage_status,t.title "
            "FROM coding_develop_threads d "
            "JOIN threads t ON t.id=d.thread_id WHERE d.thread_id=? AND d.deleted_at IS NULL", (thread_id,)
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
        connection.execute(
            "UPDATE coding_develop_threads SET archived_at=NULL, deleted_at=NULL "
            "WHERE thread_id=? AND (archived_at IS NOT NULL OR deleted_at IS NOT NULL)",
            (thread_id,)
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


def register_conversation_thread(thread_id: str, repository: str = "", title: str = ""):
    """Surface a chat-originated coding job thread in the Develop tab hierarchy."""
    ensure_schema()
    safe_repo = ""
    if repository:
        try:
            safe_repo = _repository(repository)
        except Exception:
            safe_repo = ""
    with db.write_transaction() as connection:
        if title:
            connection.execute(
                "UPDATE threads SET title=? WHERE id=? AND (title IS NULL OR title='')",
                (title[:160], thread_id)
            )
        connection.execute(
            "INSERT OR IGNORE INTO coding_develop_threads(thread_id,repository,created_at) VALUES(?,?,?)",
            (thread_id, safe_repo, db.now_iso())
        )
        connection.execute(
            "UPDATE coding_develop_threads SET archived_at=NULL, deleted_at=NULL "
            "WHERE thread_id=? AND (archived_at IS NOT NULL OR deleted_at IS NOT NULL)",
            (thread_id,)
        )
    return _row(thread_id)


def sync_chat_threads():
    """Backfill missing develop threads for chat-originated coding jobs."""
    with db.get_connection() as connection:
        has_routes = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='coding_job_routes'"
        ).fetchone()
        if not has_routes:
            return
        rows = connection.execute(
            "SELECT r.thread_id, j.repository, j.goal, j.created_at "
            "FROM coding_job_routes r "
            "JOIN coding_jobs j ON j.id=r.job_id "
            "JOIN threads t ON t.id=r.thread_id "
            "LEFT JOIN coding_develop_threads d ON d.thread_id=r.thread_id "
            "WHERE d.thread_id IS NULL AND r.thread_id IS NOT NULL AND r.thread_id != ''"
        ).fetchall()
    if not rows:
        return
    with db.write_transaction() as connection:
        for row in rows:
            thread_id = row["thread_id"]
            safe_repo = ""
            if row["repository"]:
                try:
                    safe_repo = _repository(row["repository"])
                except Exception:
                    safe_repo = ""
            title = (row["goal"] or "").strip()[:120]
            if title:
                connection.execute(
                    "UPDATE threads SET title=? WHERE id=? AND (title IS NULL OR title='')",
                    (title[:160], thread_id)
                )
            connection.execute(
                "INSERT OR IGNORE INTO coding_develop_threads(thread_id,repository,created_at) VALUES(?,?,?)",
                (thread_id, safe_repo, row["created_at"] or db.now_iso())
            )


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


_TRIAGE_ORDER = {"review_later": 0, "active": 1, "completed": 2}


def list_threads(repository=None, limit=100):
    ensure_schema()
    limit = max(1, min(int(limit), 200))
    query = (
        "SELECT d.thread_id,d.repository,d.created_at,COALESCE(d.triage_status,'active') AS triage_status,t.title "
        "FROM coding_develop_threads d "
        "JOIN threads t ON t.id=d.thread_id WHERE d.archived_at IS NULL AND d.deleted_at IS NULL"
    )
    params = []
    if repository is not None:
        query += " AND d.repository=?"
        params.append(_repository(repository))
    query += " ORDER BY d.created_at DESC LIMIT ?"
    params.append(limit)
    with db.get_connection() as connection:
        rows = [dict(r) for r in connection.execute(query, params)]
        for row in rows:
            row["latest_job"] = _latest(connection, row["thread_id"])
    rows.sort(
        key=lambda row: ((row["latest_job"] or {}).get("updated_at") or row["created_at"], row["created_at"]),
        reverse=True,
    )
    rows.sort(key=lambda row: _TRIAGE_ORDER.get(row.get("triage_status") or "active", 1))
    return rows


def update(thread_id: str, *, title: str | None = None, triage_status: str | None = None):
    """Update thread title and/or Develop triage status."""
    ensure_schema()
    _row(thread_id)
    if triage_status is not None and triage_status not in TRIAGE_STATUSES:
        raise ValueError("不正なスレッド状態です。")
    if title is not None:
        conversation_store.update_thread_title(thread_id, title)
    if triage_status is not None:
        with db.write_transaction() as connection:
            connection.execute(
                "UPDATE coding_develop_threads SET triage_status=? WHERE thread_id=? AND deleted_at IS NULL",
                (triage_status, thread_id),
            )
    return _row(thread_id)


def delete(thread_id: str) -> dict:
    """Soft-delete a Develop thread from the list while preserving underlying job records."""
    ensure_schema()
    _row(thread_id)
    now = db.now_iso()
    with db.write_transaction() as connection:
        connection.execute(
            "UPDATE coding_develop_threads SET deleted_at=? WHERE thread_id=? AND deleted_at IS NULL",
            (now, thread_id),
        )
    return {"ok": True, "thread_id": thread_id}


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
                "SELECT COUNT(*) FROM coding_develop_threads WHERE repository=? AND archived_at IS NULL AND deleted_at IS NULL", (path,)
            ).fetchone()[0]
            root["observed_at"] = db.now_iso()
    return roots
