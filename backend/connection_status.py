"""On-demand connection diagnostics; opening the menu never contacts a provider."""
from __future__ import annotations

import os
import re
import threading
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import HTTPException

from . import config, db, github_config, linkraft_config, task_sync_queue

NAMES = {"lmstudio": "LM Studio", "notion": "Notion", "calendar": "Google Calendar (ICS)",
         "github": "GitHub", "linkraft": "Linkraft", "aivis": "AivisSpeech", "brain": "BRAIN"}
_LOCKS = {key: threading.Lock() for key in NAMES}


def safe_text(value: Any) -> str | None:
    """Redact known credentials and common credential/URL patterns, never API bodies."""
    if value is None:
        return None
    text = str(value)
    secrets = [str(v) for k, v in vars(config).items()
               if any(part in k for part in ("TOKEN", "KEY", "SECRET", "PASSWORD")) and isinstance(v, str) and v]
    secrets += [github_config.TOKEN, linkraft_config.READ_TOKEN]
    secrets += [v for k, v in os.environ.items() if any(p in k.upper() for p in ("TOKEN", "KEY", "SECRET", "PASSWORD")) and v]
    for secret in sorted(set(secrets), key=len, reverse=True):
        if secret:
            text = text.replace(secret, "[非表示]")
    text = re.sub(r"https?://[^\s<>\"']+", "[URL非表示]", text)
    text = re.sub(r"(?i)(bearer\s+)[^\s,;]+", r"\1[非表示]", text)
    text = re.sub(r"(?i)((?:api[_-]?key|token|secret|password|authorization)[\"']?\s*[:=]\s*[\"']?)[^\s,;\"']+", r"\1[非表示]", text)
    text = re.sub(r"\b(?:secret_|ntn_|gh[pousr]_|github_pat_|sk-)[A-Za-z0-9_-]+", "[非表示]", text)
    return text[:600]


def _ensure_schema() -> None:
    with db.get_connection() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS connection_diagnostics (service TEXT PRIMARY KEY, "
                     "checked_at TEXT, last_success_at TEXT, last_failure_at TEXT, error TEXT, error_code TEXT)")


def _old(at: str | None, ttl: float = 300) -> bool:
    if not at:
        return True
    try:
        parsed = datetime.fromisoformat(at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - parsed).total_seconds() > ttl
    except ValueError:
        return True


def _configured(service: str) -> bool:
    return {"lmstudio": lambda: bool(config.LM_BASE_URL), "notion": config.notion_configured,
            "calendar": lambda: bool(config.CALENDAR_ICS_URLS), "github": github_config.configured,
            "linkraft": linkraft_config.configured,
            "aivis": lambda: config.TTS_PROVIDER == "aivis" and bool(config.TTS_BASE_URL),
            "brain": lambda: bool(config.OBSIDIAN_VAULT_DIRS)}[service]()


def _histories(service: str) -> list[dict[str, Any]]:
    prefixes = {"notion": ("notion:tasks",), "calendar": ("google_ics:",),
                "github": ("github:repo:",), "linkraft": ("linkraft:",)}
    states = [row for row in db.all_sync_states() if row["source"].startswith(prefixes.get(service, ("__none__",)))]
    if service == "notion":
        from .notion_task_sync import store
        states.append(store.state())
    return states


def _notion_operations() -> tuple[list[dict[str, Any]], dict[str, int]]:
    task_sync_queue.ensure_task_sync_schema()
    with db.get_connection() as conn:
        counts = {row["status"]: row["n"] for row in conn.execute(
            "SELECT status, count(*) n FROM task_sync_queue WHERE status IN ('failed','conflict','pending','processing') GROUP BY status")}
        # All unresolved operations, not the most recent N successful writes.
        rows = conn.execute("SELECT q.id, q.task_id, t.title, q.operation, q.status, q.attempts, "
                            "q.last_attempt_at, q.next_attempt_at, q.last_error, q.updated_at "
                            "FROM task_sync_queue q LEFT JOIN tasks_cache t ON t.id=q.task_id "
                            "WHERE q.status IN ('failed','conflict','pending','processing') ORDER BY q.id DESC").fetchall()
    operations = []
    for row in rows:
        item = dict(row)
        item["title"] = safe_text(item["title"]) or "削除済みタスク"
        item["error_code"] = _code(item["last_error"])
        item["last_error"] = safe_text(item["last_error"])
        item["max_attempts"] = task_sync_queue._MAX_ATTEMPTS
        if item["attempts"] >= item["max_attempts"] or item["status"] == "conflict":
            item["next_attempt_at"] = None
        operations.append(item)
    return operations, counts


def _code(error: Any) -> str | None:
    match = re.search(r"\b([45]\d\d)\b", str(error or ""))
    return match.group(1) if match else None


def _service(service: str) -> dict[str, Any]:
    configured = _configured(service)
    histories = _histories(service)
    with db.get_connection() as conn:
        row = conn.execute("SELECT * FROM connection_diagnostics WHERE service=?", (service,)).fetchone()
    diag = dict(row or {})
    success = max((s["last_success_at"] for s in histories if s.get("last_success_at")), default=None)
    failures = [s for s in histories if s.get("last_error")]
    failure = max(failures, key=lambda s: s.get("last_failure_at") or "", default={})
    error = failure.get("last_error")
    counts: dict[str, int] = {}
    operations = []
    if service == "notion":
        operations, counts = _notion_operations()
        failed = [o for o in operations if o.get("last_error")]
        if failed:
            failure = max(failed, key=lambda o: o["updated_at"] or "")
            error = failure["last_error"]
    connection = ("unconfigured" if not configured else "unverified" if not diag.get("checked_at")
                  else "error" if diag.get("error") else "stale" if _old(diag["checked_at"]) else "connected")
    syncing = counts.get("pending", 0) + counts.get("processing", 0)
    ttl = config.NOTION_TASK_PULL_INTERVAL_SECONDS * 2 if service == "notion" else 300
    sync = ("unconfigured" if not configured else "conflict" if counts.get("conflict") else "error" if error
            else "syncing" if syncing else "unverified" if not success
            else "stale" if _old(success, ttl) else "healthy") if service in {"notion", "calendar", "github", "linkraft"} else None
    return {"id": service, "name": NAMES[service], "configured": configured,
            "connection_status": connection, "sync_status": sync,
            "last_connection_success_at": diag.get("last_success_at"), "checked_at": diag.get("checked_at"),
            "last_sync_success_at": success, "last_error_at": max(filter(None, [diag.get("last_failure_at"), failure.get("last_failure_at") or failure.get("updated_at")]), default=None),
            "error": safe_text(error or diag.get("error")), "error_code": _code(error) or diag.get("error_code"),
            "failed_count": counts.get("failed", 0) or len(failures), "conflict_count": counts.get("conflict", 0),
            "operations": operations, "can_check": configured,
            "note": "接続確認は同期を実行しません。履歴のない時刻は未記録です。"}


def snapshot() -> dict[str, Any]:
    _ensure_schema()
    services = []
    for key, name in NAMES.items():
        try:
            services.append(_service(key))
        except Exception:
            services.append({"id": key, "name": name, "connection_status": "unverified", "sync_status": None,
                             "error": "保存済み状態を読み取れませんでした。サーバーログとDBを確認してください。", "can_check": False})
    return {"services": services, "generated_at": db.now_iso()}


def _probe(service: str) -> None:
    """One bounded read request; never run an integration sync or a task write."""
    if service == "brain":
        if not all(path.is_dir() for path in config.OBSIDIAN_VAULT_DIRS):
            raise ValueError("BRAINの保存フォルダが見つかりません。Vault設定を確認してください。")
        for path in config.OBSIDIAN_VAULT_DIRS:
            next(path.iterdir(), None)
        from . import vault_indexer
        if vault_indexer.status().get("indexed_chunks") is None:
            raise ValueError("BRAINの検索索引へ接続できません。")
        return
    headers = {}
    url = ""
    if service == "lmstudio":
        url = config.LM_BASE_URL.rstrip("/") + "/models"
        headers = {"Authorization": f"Bearer {config.LM_API_KEY}"}
    elif service == "notion":
        from . import notion_client
        url = notion_client._BASE + "/users/me"
        headers = notion_client._headers()
    elif service == "github":
        from . import github_client
        url = github_config.API_URL + "/user"
        headers = github_client._headers()
    elif service == "linkraft":
        from . import linkraft_client
        url = linkraft_config.BASE_URL + "/api/integrations/petit/projects"
        headers = linkraft_client._headers()
    elif service == "aivis":
        url = config.TTS_BASE_URL.rstrip("/") + "/speakers"
    elif service == "calendar":
        # A HEAD validates access to each private ICS feed without downloading/syncing events.
        for url in config.CALENDAR_ICS_URLS:
            with httpx.Client(timeout=5, follow_redirects=True) as client:
                response = client.head(url)
                response.raise_for_status()
        return
    with httpx.Client(timeout=5) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        valid = (isinstance(data, list) and bool(data)) if service == "aivis" else (
            isinstance(data, dict) and (
                isinstance(data.get("data"), list) if service == "lmstudio" else
                isinstance(data.get("projects"), list) if service == "linkraft" else
                bool(data.get("id")) if service == "notion" else bool(data.get("login"))))
        if not valid:
            raise ValueError("APIの応答形式が不正です。サービスの設定を確認してください。")


def check(service: str) -> dict[str, Any]:
    if service not in NAMES:
        raise HTTPException(404, "対象サービスがありません。")
    if not _configured(service):
        raise HTTPException(409, "未設定です。Settingsと環境設定を確認してください。")
    if not _LOCKS[service].acquire(blocking=False):
        raise HTTPException(409, "このサービスは接続確認中です。")
    try:
        _ensure_schema()
        with db.get_connection() as conn:
            previous = conn.execute("SELECT checked_at FROM connection_diagnostics WHERE service=?", (service,)).fetchone()
        if previous and not _old(previous["checked_at"], 10):
            return _service(service)
        error = code = None
        try:
            _probe(service)
        except httpx.HTTPStatusError as exc:
            code = str(exc.response.status_code)
            hint = {"401": "認証情報", "403": "連携への共有・アクセス権", "404": "接続先・共有設定", "429": "APIの利用制限"}.get(code, "外部サービスの稼働状況")
            error = f"{NAMES[service]} API HTTP {code}。{hint}を確認してください。"
        except httpx.HTTPError:
            code, error = "connection_error", "通信に失敗しました。サービスの起動、接続先、ネットワークを確認してください。"
        except Exception:
            code, error = "invalid_response", "接続確認に失敗しました。応答形式または保存フォルダのアクセス権を確認してください。"
        now = db.now_iso()
        with db.get_connection() as conn:
            conn.execute("INSERT INTO connection_diagnostics(service, checked_at, last_success_at, last_failure_at, error, error_code) "
                         "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(service) DO UPDATE SET checked_at=excluded.checked_at, "
                         "last_success_at=COALESCE(excluded.last_success_at, connection_diagnostics.last_success_at), "
                         "last_failure_at=COALESCE(excluded.last_failure_at, connection_diagnostics.last_failure_at), "
                         "error=excluded.error, error_code=excluded.error_code",
                         (service, now, None if error else now, now if error else None, error, code))
        return _service(service)
    finally:
        _LOCKS[service].release()
