"""Minimal read-only GitHub REST client for project evidence.

The client retrieves repository metadata, default-branch commits, pull requests,
check runs for newly seen commits, and deployment statuses. It performs no writes.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import httpx

from . import github_config

_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class GitHubEvidenceError(RuntimeError):
    """Raised when GitHub evidence cannot be read safely."""


def normalize_repository(value: str) -> str:
    repository = value.strip().removesuffix(".git")
    for prefix in ("https://github.com/", "http://github.com/", "git@github.com:"):
        if repository.startswith(prefix):
            repository = repository[len(prefix):]
            break
    repository = repository.strip("/")
    if not _REPOSITORY_RE.fullmatch(repository):
        raise GitHubEvidenceError("GitHub repository must use owner/name format")
    return repository


def _headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": github_config.API_VERSION,
        "User-Agent": "PETIT-project-continuity",
    }
    if github_config.TOKEN:
        headers["Authorization"] = f"Bearer {github_config.TOKEN}"
    return headers


def _safe_error(exc: Exception) -> str:
    text = str(exc)
    if github_config.TOKEN:
        text = text.replace(github_config.TOKEN, "[redacted]")
    return text[:300] or "GitHub API request failed"


def _get(path: str, params: dict[str, Any] | None = None, timeout: float = 20) -> Any:
    try:
        response = httpx.get(
            f"{github_config.API_URL}{path}",
            params=params,
            headers=_headers(),
            timeout=timeout,
            follow_redirects=True,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        body = exc.response.text[:200]
        raise GitHubEvidenceError(f"GitHub API error {status}: {body}") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise GitHubEvidenceError(_safe_error(exc)) from exc


def _is_after(value: str | None, since: str | None) -> bool:
    if not since or not value:
        return True
    try:
        left = datetime.fromisoformat(value.replace("Z", "+00:00"))
        right = datetime.fromisoformat(since.replace("Z", "+00:00"))
    except ValueError:
        return True
    if left.tzinfo is None:
        left = left.replace(tzinfo=timezone.utc)
    if right.tzinfo is None:
        right = right.replace(tzinfo=timezone.utc)
    return left > right


def _bounded_since(since: str | None) -> str:
    if since:
        return since
    return (
        datetime.now(timezone.utc) - timedelta(days=github_config.INITIAL_LOOKBACK_DAYS)
    ).replace(microsecond=0).isoformat()


def get_repository(repository: str) -> dict[str, Any]:
    full_name = normalize_repository(repository)
    data = _get(f"/repos/{quote(full_name, safe='/')}")
    if not isinstance(data, dict) or not data.get("full_name"):
        raise GitHubEvidenceError("GitHub returned invalid repository metadata")
    return data


def list_commits(repository: str, *, branch: str, since: str | None) -> list[dict[str, Any]]:
    full_name = normalize_repository(repository)
    items: list[dict[str, Any]] = []
    params: dict[str, Any] = {
        "sha": branch,
        "since": _bounded_since(since),
        "per_page": 100,
    }
    for page in range(1, github_config.MAX_PAGES + 1):
        data = _get(f"/repos/{quote(full_name, safe='/')}/commits", params=params | {"page": page})
        if not isinstance(data, list):
            raise GitHubEvidenceError("GitHub returned invalid commit data")
        items.extend(item for item in data if isinstance(item, dict))
        if len(data) < 100:
            break
    return items


def list_pull_requests(repository: str, *, since: str | None) -> list[dict[str, Any]]:
    full_name = normalize_repository(repository)
    items: list[dict[str, Any]] = []
    for page in range(1, github_config.MAX_PAGES + 1):
        data = _get(
            f"/repos/{quote(full_name, safe='/')}/pulls",
            params={
                "state": "all",
                "sort": "updated",
                "direction": "desc",
                "per_page": 100,
                "page": page,
            },
        )
        if not isinstance(data, list):
            raise GitHubEvidenceError("GitHub returned invalid pull request data")
        page_items = [item for item in data if isinstance(item, dict)]
        items.extend(item for item in page_items if _is_after(item.get("updated_at"), since))
        if len(data) < 100 or (since and page_items and not _is_after(page_items[-1].get("updated_at"), since)):
            break
    return items


def list_check_runs(repository: str, commits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    full_name = normalize_repository(repository)
    result: list[dict[str, Any]] = []
    for commit in commits[: github_config.MAX_CHECK_COMMITS]:
        sha = str(commit.get("sha") or "").strip()
        if not sha:
            continue
        data = _get(
            f"/repos/{quote(full_name, safe='/')}/commits/{quote(sha, safe='')}/check-runs",
            params={"per_page": 100},
        )
        if not isinstance(data, dict):
            raise GitHubEvidenceError("GitHub returned invalid check run data")
        for item in data.get("check_runs") or []:
            if isinstance(item, dict):
                item = dict(item)
                item["commit_sha"] = sha
                result.append(item)
    return result


def list_deployments(repository: str, *, since: str | None) -> list[dict[str, Any]]:
    full_name = normalize_repository(repository)
    result: list[dict[str, Any]] = []
    for page in range(1, github_config.MAX_PAGES + 1):
        data = _get(
            f"/repos/{quote(full_name, safe='/')}/deployments",
            params={"per_page": 100, "page": page},
        )
        if not isinstance(data, list):
            raise GitHubEvidenceError("GitHub returned invalid deployment data")
        page_items = [item for item in data if isinstance(item, dict)]
        selected = [
            item
            for item in page_items
            if _is_after(item.get("updated_at") or item.get("created_at"), since)
        ]
        for deployment in selected:
            deployment_id = deployment.get("id")
            if deployment_id is None:
                continue
            statuses = _get(
                f"/repos/{quote(full_name, safe='/')}/deployments/{deployment_id}/statuses",
                params={"per_page": 100},
            )
            if not isinstance(statuses, list):
                raise GitHubEvidenceError("GitHub returned invalid deployment status data")
            item = dict(deployment)
            item["statuses"] = [status for status in statuses if isinstance(status, dict)]
            item["latest_status"] = item["statuses"][0] if item["statuses"] else None
            result.append(item)
        if len(data) < 100 or (since and page_items and not _is_after(
            page_items[-1].get("updated_at") or page_items[-1].get("created_at"), since
        )):
            break
    return result


def get_repository_evidence(repository: str, since: str | None = None) -> dict[str, Any]:
    """Return a bounded evidence snapshot and a race-safe next cursor."""
    snapshot_started_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    metadata = get_repository(repository)
    full_name = normalize_repository(str(metadata["full_name"]))
    default_branch = str(metadata.get("default_branch") or "main")
    commits = list_commits(full_name, branch=default_branch, since=since)
    pulls = list_pull_requests(full_name, since=since)
    checks = list_check_runs(full_name, commits)
    deployments = list_deployments(full_name, since=since)
    return {
        "source": "github",
        "repository": metadata,
        "since": since,
        "nextSince": snapshot_started_at,
        "commits": commits,
        "pullRequests": pulls,
        "checkRuns": checks,
        "deployments": deployments,
    }
