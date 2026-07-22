"""Daily cross-repository GitHub catch-up for PETIT.

The project-scoped GitHub evidence adapter answers "what is verified for this
project?". This module answers a different personal-assistant question:
"what changed across my development repositories since the last review?"

It is read-only, uses a global review cursor, caches the latest result in SQLite,
and can run both from a morning scheduler and an explicit conversation tool.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import config, db, github_config  # config import ensures project .env is loaded
from .github_activity import get_repository_activity, list_accessible_repositories
from .lmstudio_client import LMStudioError, chat_completion

log = logging.getLogger(__name__)

REVIEW_ENABLED = os.getenv("PETIT_GITHUB_DAILY_REVIEW_ENABLED", "1") not in ("0", "false", "False")
REVIEW_HOUR = max(0, min(23, int(os.getenv("PETIT_GITHUB_DAILY_REVIEW_HOUR", "8"))))
REVIEW_POLL_MINUTES = max(1, min(180, int(os.getenv("PETIT_GITHUB_DAILY_REVIEW_POLL_MINUTES", "15"))))
REVIEW_LOOKBACK_HOURS = max(1, min(24 * 30, int(os.getenv("PETIT_GITHUB_DAILY_REVIEW_LOOKBACK_HOURS", "24"))))
REVIEW_MAX_REPOSITORIES = max(1, min(100, int(os.getenv("PETIT_GITHUB_DAILY_REVIEW_MAX_REPOSITORIES", "50"))))
REVIEW_MAX_COMMITS_PER_REPO = max(1, min(30, int(os.getenv("PETIT_GITHUB_DAILY_REVIEW_MAX_COMMITS_PER_REPO", "10"))))
REVIEW_PROGRESS_MAX_CHARS = max(200, min(8000, int(os.getenv("PETIT_GITHUB_DAILY_REVIEW_PROGRESS_MAX_CHARS", "1800"))))
REVIEW_INCLUDE_FORKS = os.getenv("PETIT_GITHUB_DAILY_REVIEW_INCLUDE_FORKS", "0") not in ("0", "false", "False")
REVIEW_TIMEZONE_NAME = os.getenv("PETIT_GITHUB_DAILY_REVIEW_TIMEZONE", "Asia/Tokyo").strip() or "Asia/Tokyo"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS github_daily_review_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    since_at TEXT,
    next_since TEXT,
    cursor_advanced INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    repository_count INTEGER NOT NULL DEFAULT 0,
    changed_count INTEGER NOT NULL DEFAULT 0,
    result_json TEXT NOT NULL DEFAULT '{}',
    message TEXT NOT NULL DEFAULT '',
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_github_daily_review_completed
ON github_daily_review_runs(completed_at DESC, id DESC);
"""

_SYSTEM = """あなたはPETIT。GitHubの取得済み事実だけを使い、前回以降の開発差分を日本語でレビューしてください。
ルール:
- 事実と推測を分ける。確認できない完了・品質・動作を断定しない。
- 変更があったrepositoryだけ扱う。
- 重要度順に、結論、注意点、次の一手を短く示す。
- 失敗または進行中のcheckを最優先する。
- PROGRESS.mdとcommit/PR/checkが食い違う可能性があれば、その可能性を明示する。
- 5〜12行程度。内部の思考過程は出さない。"""

_run_lock = threading.Lock()


def _timezone() -> ZoneInfo:
    try:
        return ZoneInfo(REVIEW_TIMEZONE_NAME)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    current = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def ensure_schema() -> None:
    with db.get_connection() as conn:
        conn.executescript(_SCHEMA)


def _decode_row(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    try:
        result = json.loads(data.get("result_json") or "{}")
    except json.JSONDecodeError:
        result = {}
    if not isinstance(result, dict):
        result = {}
    result.setdefault("status", data.get("status"))
    result.setdefault("message", data.get("message") or "")
    result.setdefault("repository_count", int(data.get("repository_count") or 0))
    result.setdefault("changed_count", int(data.get("changed_count") or 0))
    result.setdefault("since", data.get("since_at"))
    result.setdefault("next_since", data.get("next_since"))
    result.setdefault("completed_at", data.get("completed_at"))
    result.setdefault("cursor_advanced", bool(data.get("cursor_advanced")))
    if data.get("error") and not result.get("error"):
        result["error"] = data["error"]
    return result


def latest_review() -> dict[str, Any] | None:
    ensure_schema()
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM github_daily_review_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return _decode_row(row)


def _latest_cursor() -> str | None:
    ensure_schema()
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT next_since FROM github_daily_review_runs "
            "WHERE cursor_advanced = 1 AND next_since IS NOT NULL "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return str(row["next_since"]) if row and row["next_since"] else None


def _completed_today(now: datetime) -> dict[str, Any] | None:
    latest = latest_review()
    if not latest or latest.get("status") in {"error", "not_configured", "disabled"}:
        return None
    completed = _parse(str(latest.get("completed_at") or ""))
    if completed is None:
        return None
    if completed.astimezone(_timezone()).date() != now.astimezone(_timezone()).date():
        return None
    return latest


def _record(result: dict[str, Any], started_at: str, completed_at: str) -> None:
    ensure_schema()
    payload = dict(result)
    payload.pop("cached", None)
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO github_daily_review_runs "
            "(started_at, completed_at, since_at, next_since, cursor_advanced, status, "
            "repository_count, changed_count, result_json, message, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                started_at,
                completed_at,
                result.get("since"),
                result.get("next_since"),
                int(bool(result.get("cursor_advanced"))),
                str(result.get("status") or "error"),
                int(result.get("repository_count") or 0),
                int(result.get("changed_count") or 0),
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                str(result.get("message") or ""),
                str(result.get("error") or "") or None,
            ),
        )


def _eligible_repository(item: dict[str, Any]) -> bool:
    if item.get("archived") or item.get("disabled"):
        return False
    if not REVIEW_INCLUDE_FORKS and item.get("fork"):
        return False
    if item.get("size") in (0, "0") and not item.get("pushed_at"):
        return False
    return bool(item.get("full_name"))


def _commit(item: dict[str, Any]) -> dict[str, Any]:
    commit = item.get("commit") if isinstance(item.get("commit"), dict) else {}
    author = commit.get("author") if isinstance(commit.get("author"), dict) else {}
    committer = commit.get("committer") if isinstance(commit.get("committer"), dict) else {}
    message = str(commit.get("message") or "").strip()
    return {
        "sha": str(item.get("sha") or ""),
        "message": message.splitlines()[0] if message else "Commit",
        "author": author.get("name"),
        "occurred_at": committer.get("date") or author.get("date"),
        "url": item.get("html_url"),
    }


def _pull(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": item.get("number"),
        "title": str(item.get("title") or "Pull request"),
        "state": "merged" if item.get("merged_at") else str(item.get("state") or "unknown"),
        "draft": bool(item.get("draft")),
        "updated_at": item.get("updated_at"),
        "merged_at": item.get("merged_at"),
        "url": item.get("html_url"),
    }


def _check(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(item.get("name") or "check"),
        "status": str(item.get("status") or "unknown"),
        "conclusion": item.get("conclusion"),
        "sha": str(item.get("head_sha") or item.get("commit_sha") or ""),
        "updated_at": item.get("completed_at") or item.get("started_at"),
        "url": item.get("html_url"),
    }


def _compact_activity(snapshot: dict[str, Any]) -> dict[str, Any]:
    metadata = snapshot.get("repository") if isinstance(snapshot.get("repository"), dict) else {}
    commits = [
        _commit(item)
        for item in (snapshot.get("commits") or [])[:REVIEW_MAX_COMMITS_PER_REPO]
        if isinstance(item, dict)
    ]
    pulls = [_pull(item) for item in snapshot.get("pull_requests") or [] if isinstance(item, dict)]
    checks = [_check(item) for item in snapshot.get("check_runs") or [] if isinstance(item, dict)]
    progress = str(snapshot.get("progress") or "").strip()
    failed_checks = [
        item for item in checks if item.get("conclusion") in {"failure", "timed_out", "action_required", "startup_failure", "cancelled"}
    ]
    pending_checks = [
        item for item in checks if item.get("status") != "completed" or item.get("conclusion") is None
    ]
    return {
        "full_name": str(snapshot.get("full_name") or metadata.get("full_name") or ""),
        "url": metadata.get("html_url"),
        "default_branch": snapshot.get("default_branch") or metadata.get("default_branch"),
        "commits": commits,
        "pull_requests": pulls,
        "checks": checks,
        "failed_checks": failed_checks,
        "pending_checks": pending_checks,
        "progress_found": bool(progress),
        "progress_excerpt": progress[:REVIEW_PROGRESS_MAX_CHARS],
        "progress_error": snapshot.get("progress_error"),
    }


def _priority(repositories: list[dict[str, Any]]) -> str:
    if any(repo.get("failed_checks") for repo in repositories):
        return "high"
    if any(repo.get("pending_checks") for repo in repositories):
        return "medium"
    return "normal"


def _next_action(repositories: list[dict[str, Any]]) -> str:
    for repo in repositories:
        failed = repo.get("failed_checks") or []
        if failed:
            return f"{repo['full_name']} の失敗CI「{failed[0]['name']}」を確認する"
    for repo in repositories:
        pending = repo.get("pending_checks") or []
        if pending:
            return f"{repo['full_name']} の実行中check「{pending[0]['name']}」を確認する"
    for repo in repositories:
        pulls = repo.get("pull_requests") or []
        open_pulls = [item for item in pulls if item.get("state") == "open"]
        if open_pulls:
            return f"{repo['full_name']} のPR #{open_pulls[0]['number']}を確認する"
    for repo in repositories:
        commits = repo.get("commits") or []
        if commits:
            return f"{repo['full_name']} の最新commit差分を確認する"
    return "今日進めるrepositoryを1つ決める"


def _fallback_message(
    repositories: list[dict[str, Any]],
    *,
    since: str,
    errors: list[dict[str, str]],
    next_action: str,
) -> str:
    if not repositories:
        if errors:
            return f"GitHub差分の取得に失敗しました。{errors[0]['repository']}: {errors[0]['error']}"
        return "GitHubでは前回の確認以降、対象リポジトリに新しい開発差分はありません。"

    lines = [f"GitHubの前回差分は{len(repositories)}リポジトリです（基準: {since}）。"]
    for repo in repositories[:8]:
        commits = repo.get("commits") or []
        pulls = repo.get("pull_requests") or []
        failed = repo.get("failed_checks") or []
        pending = repo.get("pending_checks") or []
        parts = [f"commit {len(commits)}件", f"PR更新 {len(pulls)}件"]
        if failed:
            parts.append(f"失敗check {len(failed)}件")
        if pending:
            parts.append(f"進行中check {len(pending)}件")
        latest = f" / 最新: {commits[0]['message']}" if commits else ""
        if repo.get("progress_found"):
            progress = " / PROGRESSあり"
        elif repo.get("progress_error"):
            progress = " / PROGRESS取得失敗"
        else:
            progress = " / PROGRESSなし"
        lines.append(f"- {repo['full_name']}: {', '.join(parts)}{latest}{progress}")
    if len(repositories) > 8:
        lines.append(f"- ほか{len(repositories) - 8}リポジトリ")
    if errors:
        lines.append(f"- 取得失敗: {len(errors)}リポジトリ（cursorは進めていません）")
    lines.append(f"次の一手: {next_action}")
    return "\n".join(lines)


def _llm_context(
    repositories: list[dict[str, Any]],
    *,
    since: str,
    errors: list[dict[str, str]],
    next_action: str,
) -> str:
    payload = {
        "since": since,
        "changed_repositories": repositories,
        "errors": errors,
        "suggested_next_action": next_action,
        "boundaries": [
            "commitは実装全体の完了証明ではない",
            "check成功は実画面・本番確認を証明しない",
            "PROGRESS.mdは自己申告でありGitHub事実と照合する",
        ],
    }
    text = json.dumps(payload, ensure_ascii=False, default=str)
    return text[:30000]


def _generate_message(
    repositories: list[dict[str, Any]],
    *,
    since: str,
    errors: list[dict[str, str]],
    next_action: str,
) -> tuple[str, str]:
    fallback = _fallback_message(repositories, since=since, errors=errors, next_action=next_action)
    if not repositories:
        return fallback, "template"
    try:
        message = chat_completion(
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": _llm_context(repositories, since=since, errors=errors, next_action=next_action)},
            ],
            tools=None,
            temperature=0.2,
            max_tokens=700,
            route="agent",
        )
        text = str(message.get("content") or "").strip()
        if text:
            return text, "llm"
    except LMStudioError as exc:
        log.debug("GitHub daily review via LM Studio failed: %s", exc)
    return fallback, "template"


def run_review(
    *,
    force: bool = False,
    repositories_loader: Callable[[], list[dict[str, Any]]] | None = None,
    activity_loader: Callable[[dict[str, Any], str | None], dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Collect and review changes since the last successful global cursor."""
    current = now or _utc_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    if not REVIEW_ENABLED:
        return {"status": "disabled", "message": "GitHub朝レビューは無効です。", "changed_count": 0}
    if repositories_loader is None and not github_config.configured():
        return {
            "status": "not_configured",
            "message": "GitHub朝レビューを使うにはPETIT_GITHUB_TOKENを設定してください。",
            "changed_count": 0,
        }

    with _run_lock:
        if not force:
            cached = _completed_today(current)
            if cached is not None:
                return {**cached, "cached": True}

        started = _iso(current)
        previous_cursor = _latest_cursor()
        since = previous_cursor or _iso(current - timedelta(hours=REVIEW_LOOKBACK_HOURS))
        next_since = started
        repo_loader = repositories_loader or list_accessible_repositories
        detail_loader = activity_loader or (
            lambda metadata, cursor: get_repository_activity(
                metadata,
                cursor,
                progress_max_chars=REVIEW_PROGRESS_MAX_CHARS,
            )
        )

        try:
            repositories = [
                item
                for item in repo_loader()
                if isinstance(item, dict) and _eligible_repository(item)
            ][:REVIEW_MAX_REPOSITORIES]
        except Exception as exc:  # noqa: BLE001
            error = _safe_error(exc)
            result = {
                "status": "error",
                "message": f"GitHubリポジトリ一覧の取得に失敗しました。{error}",
                "repository_count": 0,
                "changed_count": 0,
                "repositories": [],
                "errors": [{"repository": "repository-list", "error": error}],
                "since": since,
                "next_since": previous_cursor,
                "cursor_advanced": False,
                "priority": "high",
                "next_action": "GitHub tokenとAPI接続を確認する",
                "error": error,
                "kind": "template",
            }
            _record(result, started, _iso(current))
            return result

        changed: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for metadata in repositories:
            full_name = str(metadata.get("full_name") or "unknown")
            try:
                snapshot = detail_loader(metadata, since)
                if snapshot.get("changed") or snapshot.get("commits") or snapshot.get("pull_requests") or snapshot.get("check_runs"):
                    changed.append(_compact_activity(snapshot))
                for source_error in snapshot.get("source_errors") or []:
                    if not isinstance(source_error, dict):
                        continue
                    source = str(source_error.get("source") or "activity")
                    error = _safe_error(RuntimeError(str(source_error.get("error") or "GitHub API request failed")))
                    errors.append({"repository": f"{full_name}:{source}", "error": error})
            except Exception as exc:  # noqa: BLE001
                errors.append({"repository": full_name, "error": _safe_error(exc)})

        next_action = _next_action(changed)
        message, kind = _generate_message(
            changed,
            since=since,
            errors=errors,
            next_action=next_action,
        )
        cursor_advanced = not errors
        status = "partial" if errors and changed else "error" if errors else "found" if changed else "no_changes"
        result = {
            "status": status,
            "message": message,
            "repository_count": len(repositories),
            "changed_count": len(changed),
            "repositories": changed,
            "errors": errors,
            "since": since,
            "next_since": next_since if cursor_advanced else previous_cursor,
            "cursor_advanced": cursor_advanced,
            "priority": _priority(changed) if changed else ("high" if errors else "normal"),
            "next_action": next_action,
            "error": "; ".join(f"{item['repository']}: {item['error']}" for item in errors) or None,
            "kind": kind,
            "cached": False,
        }
        _record(result, started, _iso(current))
        return result


def review_for_briefing(target_date: str | None = None) -> dict[str, Any]:
    """Return today's cached/run review; skip historical briefing dates."""
    local_today = datetime.now(_timezone()).date().isoformat()
    if target_date and target_date != local_today:
        return {"status": "skipped_non_today", "message": "", "changed_count": 0}
    try:
        return run_review(force=False)
    except Exception as exc:  # noqa: BLE001
        error = _safe_error(exc)
        return {
            "status": "error",
            "message": f"GitHub朝レビューを取得できませんでした。{error}",
            "changed_count": 0,
            "priority": "high",
            "next_action": "GitHub連携を確認する",
            "error": error,
        }


def _safe_error(exc: Exception) -> str:
    text = str(exc)
    if github_config.TOKEN:
        text = text.replace(github_config.TOKEN, "[redacted]")
    return text[:300] or type(exc).__name__


class GitHubDailyReviewScheduler:
    """Run one review after the configured local morning hour while PETIT is on."""

    def __init__(self, poll_minutes: int | None = None) -> None:
        self.poll_minutes = poll_minutes if poll_minutes is not None else REVIEW_POLL_MINUTES
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not REVIEW_ENABLED or not github_config.configured():
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, name="petit-github-review", daemon=True)
        self._thread.start()
        log.info(
            "GitHub daily review scheduler started (hour=%s timezone=%s poll=%sm)",
            REVIEW_HOUR,
            REVIEW_TIMEZONE_NAME,
            self.poll_minutes,
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def due(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(_timezone())
        if current.tzinfo is None:
            current = current.replace(tzinfo=_timezone())
        local = current.astimezone(_timezone())
        if local.hour < REVIEW_HOUR:
            return False
        return _completed_today(local) is None

    def run_once(self, *, force: bool = False) -> dict[str, Any]:
        return run_review(force=force)

    def _run_loop(self) -> None:
        interval_seconds = max(60.0, float(self.poll_minutes) * 60.0)
        while not self._stop.is_set():
            try:
                if self.due():
                    result = self.run_once(force=False)
                    log.info(
                        "GitHub daily review status=%s changed=%s",
                        result.get("status"),
                        result.get("changed_count"),
                    )
            except Exception as exc:  # noqa: BLE001
                log.warning("GitHub daily review tick failed: %s", _safe_error(exc))
            self._stop.wait(interval_seconds)


_scheduler: GitHubDailyReviewScheduler | None = None


def get_scheduler() -> GitHubDailyReviewScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = GitHubDailyReviewScheduler()
    return _scheduler
