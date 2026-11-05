"""Durable, read-only background research jobs (#372).

The existing SQLite jobs table is the only job ledger. A separately leased
worker processes only the new durable_read type; legacy agent_followup jobs
keep their existing (non-replayable) semantics.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import conversation_store, db, setup_api, web_sources

log = logging.getLogger(__name__)
JOB_TYPE = "durable_read"
LEASE_SECONDS = 120.0
router = APIRouter(
    prefix="/api/agent-tasks",
    tags=["agent-tasks"],
    dependencies=[Depends(setup_api._admin)],
)


class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1, max_length=200)
    thread_id: str = Field(min_length=1, max_length=200)
    kind: Literal["news", "weather"] = "news"
    query: str = Field(min_length=1, max_length=2000)


def ensure_schema() -> None:
    """Additive migration; existing jobs, approvals and receipts are preserved."""
    with db.get_connection() as conn:
        db._ensure_columns(conn, "jobs", {
            "idempotency_key": "TEXT",
            "claimed_by": "TEXT",
            "lease_expires_at": "REAL",
            "attempt_count": "INTEGER NOT NULL DEFAULT 0",
            "max_attempts": "INTEGER NOT NULL DEFAULT 3",
            "cancel_requested": "INTEGER NOT NULL DEFAULT 0",
        })
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_durable_key "
            "ON jobs(idempotency_key) WHERE type='durable_read' AND idempotency_key IS NOT NULL"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_durable_claim "
            "ON jobs(type, status, lease_expires_at, id)"
        )


def _read(row, *, include_result: bool = False) -> dict:
    item = dict(row)
    value = {
        "id": item["id"],
        "type": item["type"],
        "status": item["status"],
        "thread_id": item["session_id"],
        "request_id": item["request_id"],
        "created_at": item["created_at"],
        "updated_at": item["updated_at"],
        "attempt_count": item["attempt_count"],
        "max_attempts": item["max_attempts"],
        "cancel_requested": bool(item["cancel_requested"]),
    }
    if include_result:
        payload = json.loads(item["input_json"])
        value["kind"] = payload.get("kind")
        value["query"] = payload.get("query")
        value["result"] = (item["result_text"] or "")[:16000] if item["status"] == "done" else None
        value["error_code"] = item["error"] if item["status"] == "failed" else None
    return value


def enqueue(*, thread_id: str, request_id: str, kind: str, query: str) -> dict:
    """Insert once per original request. Identical retries return the same job."""
    if kind not in {"news", "weather"}:
        raise ValueError("unsupported_research_kind")
    query = query.strip()
    if not query or len(query) > 2000:
        raise ValueError("invalid_research_query")
    thread = conversation_store.thread(thread_id)
    if thread["privacy"] == "local_only":
        raise ValueError("local_only_external_research_forbidden")
    ensure_schema()
    payload = json.dumps({"kind": kind, "query": query}, ensure_ascii=False, sort_keys=True)
    key = thread_id + ":" + request_id
    now = db.now_iso()
    with db.write_transaction() as conn:
        old = conn.execute(
            "SELECT * FROM jobs WHERE type=? AND idempotency_key=?",
            (JOB_TYPE, key),
        ).fetchone()
        if old is not None:
            if old["input_json"] != payload:
                raise ValueError("idempotency_conflict")
            return _read(old, include_result=True)
        cursor = conn.execute(
            "INSERT INTO jobs(type,status,input_json,session_id,request_id,"
            "idempotency_key,created_at,updated_at) "
            "VALUES(?,'queued',?,?,?,?,?,?)",
            (JOB_TYPE, payload, thread_id, request_id, key, now, now),
        )
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (cursor.lastrowid,)).fetchone()
        return _read(row, include_result=True)


def get(job_id: int) -> dict:
    ensure_schema()
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE id=? AND type=?", (job_id, JOB_TYPE)
        ).fetchone()
    if row is None:
        raise ValueError("agent_task_not_found")
    return _read(row, include_result=True)


def listing(limit: int = 30) -> list[dict]:
    ensure_schema()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE type=? ORDER BY id DESC LIMIT ?",
            (JOB_TYPE, max(1, min(int(limit), 100))),
        ).fetchall()
    return [_read(row) for row in rows]


def cancel(job_id: int) -> dict:
    """Best-effort cancellation: an in-flight HTTP read may still finish."""
    ensure_schema()
    with db.write_transaction() as conn:
        conn.execute(
            "UPDATE jobs SET status='cancelled',cancel_requested=1,claimed_by=NULL,"
            "lease_expires_at=NULL,updated_at=? "
            "WHERE id=? AND type=? AND status IN ('queued','running')",
            (db.now_iso(), job_id, JOB_TYPE),
        )
    return get(job_id)


def claim(*, lease_seconds: float = LEASE_SECONDS) -> dict | None:
    ensure_schema()
    now = time.time()
    with db.write_transaction() as conn:
        conn.execute(
            "UPDATE jobs SET status='failed',error='read_task_attempts_exhausted',"
            "claimed_by=NULL,lease_expires_at=NULL,updated_at=? "
            "WHERE type=? AND status='running' AND lease_expires_at <= ? "
            "AND attempt_count >= max_attempts",
            (db.now_iso(), JOB_TYPE, now),
        )
        row = conn.execute(
            "SELECT * FROM jobs WHERE type=? AND cancel_requested=0 "
            "AND attempt_count < max_attempts AND "
            "(status='queued' OR (status='running' AND lease_expires_at <= ?)) "
            "ORDER BY id ASC LIMIT 1",
            (JOB_TYPE, now),
        ).fetchone()
        if row is None:
            return None
        token = uuid4().hex
        conn.execute(
            "UPDATE jobs SET status='running',claimed_by=?,lease_expires_at=?,"
            "attempt_count=attempt_count+1,claimed_at=?,updated_at=? WHERE id=?",
            (token, now + lease_seconds, db.now_iso(), db.now_iso(), row["id"]),
        )
        return {"id": row["id"], "token": token, "input_json": row["input_json"]}


def renew(job_id: int, token: str, *, lease_seconds: float = LEASE_SECONDS) -> bool:
    with db.get_connection() as conn:
        changed = conn.execute(
            "UPDATE jobs SET lease_expires_at=? WHERE id=? AND type=? "
            "AND claimed_by=? AND status='running' AND cancel_requested=0",
            (time.time() + lease_seconds, job_id, JOB_TYPE, token),
        ).rowcount
    return changed == 1


def finish(job_id: int, token: str, *, result: str = "", error_code: str | None = None) -> bool:
    """Fencing token prevents an expired/cancelled worker from overwriting a newer attempt."""
    status = "failed" if error_code else "done"
    with db.get_connection() as conn:
        changed = conn.execute(
            "UPDATE jobs SET status=?,result_text=?,error=?,claimed_by=NULL,"
            "lease_expires_at=NULL,updated_at=? "
            "WHERE id=? AND type=? AND status='running' AND claimed_by=? AND cancel_requested=0",
            (status, result[:16000] if not error_code else None,
             error_code, db.now_iso(), job_id, JOB_TYPE, token),
        ).rowcount
    return changed == 1


def _research(data: dict) -> str:
    if data["kind"] == "weather":
        value = web_sources.get_weather(data["query"], None)
        return web_sources.format_weather(value)
    if data["kind"] == "news":
        value = web_sources.search_news(data["query"], 5)
        return web_sources.format_news(value)
    raise ValueError("unsupported_research_kind")


def process_once(job: dict, *, lease_seconds: float = LEASE_SECONDS) -> None:
    """Perform one public read without blocking the foreground conversation executor."""
    stop = threading.Event()

    def heartbeat() -> None:
        while not stop.wait(max(1.0, lease_seconds / 3)):
            if not renew(job["id"], job["token"], lease_seconds=lease_seconds):
                return

    pulse = threading.Thread(target=heartbeat, name="petit-read-heartbeat", daemon=True)
    pulse.start()
    status = None
    try:
        result = _research(json.loads(job["input_json"]))
        if finish(job["id"], job["token"], result=result):
            status = "done"
    except Exception as exc:  # noqa: BLE001
        log.warning("durable read failed job=%s exception=%s", job["id"], type(exc).__name__)
        if finish(job["id"], job["token"], error_code="read_task_failed"):
            status = "failed"
    finally:
        stop.set()
        pulse.join(timeout=2)

    if status is not None:
        try:
            from . import notifications
            notifications.dispatch_notification(
                category="background_task",
                title="PETITの調査が完了" if status == "done" else "PETITの調査に失敗",
                body=f"調査ジョブ #{job['id']} の結果を確認できます。",
                url="/",
            )
        except Exception:  # noqa: BLE001
            log.exception("read completion notification unavailable job=%s", job["id"])


class ReadWorker:
    """Dedicated bounded worker; legacy queue and regular conversation remain responsive."""

    def __init__(self, interval_seconds: float = 2.0):
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        ensure_schema()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="petit-durable-read", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                job = claim()
                if job is not None:
                    process_once(job)
                    continue
            except Exception:  # noqa: BLE001
                log.exception("durable read loop failed")
            self._stop.wait(self.interval_seconds)


_worker = ReadWorker()


def get_worker() -> ReadWorker:
    return _worker


def _endpoint_error(exc: ValueError) -> HTTPException:
    return HTTPException(409 if str(exc) == "idempotency_conflict" else 400, str(exc))


@router.post("", status_code=202, dependencies=[Depends(setup_api._same_origin)])
def submit(payload: ResearchRequest) -> dict:
    try:
        return enqueue(**payload.model_dump())
    except ValueError as exc:
        raise _endpoint_error(exc) from None


@router.get("")
def list_tasks(limit: int = 30) -> dict:
    return {"tasks": listing(limit)}


@router.get("/{job_id}")
def detail(job_id: int) -> dict:
    try:
        return get(job_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from None


@router.post("/{job_id}/cancel", dependencies=[Depends(setup_api._same_origin)])
def cancel_task(job_id: int) -> dict:
    try:
        return cancel(job_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from None
