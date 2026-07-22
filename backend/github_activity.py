"""Read-only cross-repository GitHub activity collection for PETIT.

This module deliberately stays separate from project-scoped GitHub evidence.
It reads all repositories available to the configured token and returns bounded
activity snapshots for daily catch-up/review. It never writes to GitHub.
"""
from __future__ import annotations

import base64
from typing import Any
from urllib.parse import quote

import httpx

from . import github_client, github_config


class GitHubActivityError(RuntimeError):
    """Raised when cross-repository activity cannot be read safely."""


def list_accessible_repositories() -> list[dict[str, Any]]:
    """List repositories visible to the configured token, newest first."""
    if not github_config.configured():
        raise GitHubActivityError("GitHub token is not configured")

    items: list[dict[str, Any]] = []
    for page in range(1, github_config.MAX_PAGES + 1):
        data = github_client._get(  # noqa: SLF001 - shared internal REST helper
            "/user/repos",
            params={
                "affiliation": "owner,collaborator,organization_member",
                "visibility": "all",
                "sort": "updated",
                "direction": "desc",
                "per_page": 100,
                "page": page,
            },
        )
        if not isinstance(data, list):
            raise GitHubActivityError("GitHub returned invalid repository list data")
        page_items = [item for item in data if isinstance(item, dict)]
        items.extend(page_items)
        if len(page_items) < 100:
            break
    return items


def read_repository_text(
    repository: str,
    path: str,
    *,
    ref: str | None = None,
    max_chars: int = 4000,
) -> str | None:
    """Read one UTF-8 repository file. Missing files return ``None``."""
    full_name = github_client.normalize_repository(repository)
    safe_path = quote(path.strip("/"), safe="/")
    params = {"ref": ref} if ref else None
    try:
        response = httpx.get(
            f"{github_config.API_URL}/repos/{quote(full_name, safe='/')}/contents/{safe_path}",
            params=params,
            headers=github_client._headers(),  # noqa: SLF001 - same security boundary as evidence client
            timeout=20,
            follow_redirects=True,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPStatusError as exc:
        raise GitHubActivityError(
            f"GitHub API error {exc.response.status_code}: {exc.response.text[:200]}"
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise GitHubActivityError(github_client._safe_error(exc)) from exc  # noqa: SLF001

    if not isinstance(data, dict) or data.get("type") != "file":
        return None
    content = data.get("content")
    encoding = str(data.get("encoding") or "")
    if not isinstance(content, str):
        return None
    try:
        if encoding == "base64":
            text = base64.b64decode(content).decode("utf-8", errors="replace")
        else:
            text = content
    except (ValueError, UnicodeError) as exc:
        raise GitHubActivityError("GitHub file content could not be decoded") from exc
    return text[: max(1, int(max_chars))]


def get_repository_activity(
    metadata: dict[str, Any],
    since: str | None,
    *,
    progress_max_chars: int = 4000,
) -> dict[str, Any]:
    """Return bounded commit/PR/check activity plus optional ``PROGRESS.md``."""
    full_name = github_client.normalize_repository(str(metadata.get("full_name") or ""))
    default_branch = str(metadata.get("default_branch") or "main")
    source_errors: list[dict[str, str]] = []
    try:
        commits = github_client.list_commits(full_name, branch=default_branch, since=since)
    except Exception as exc:  # noqa: BLE001 - preserve other readable sources
        commits = []
        source_errors.append({"source": "commits", "error": github_client._safe_error(exc)})  # noqa: SLF001
    try:
        pulls = github_client.list_pull_requests(full_name, since=since)
    except Exception as exc:  # noqa: BLE001 - preserve other readable sources
        pulls = []
        source_errors.append({"source": "pull_requests", "error": github_client._safe_error(exc)})  # noqa: SLF001

    commit_refs = [str(item.get("sha") or "") for item in commits if isinstance(item, dict)]
    try:
        checks = github_client.list_check_runs(full_name, [*commit_refs, default_branch])
    except Exception as exc:  # noqa: BLE001 - commits/PRs still remain useful
        checks = []
        source_errors.append({"source": "check_runs", "error": github_client._safe_error(exc)})  # noqa: SLF001
    commit_set = {item for item in commit_refs if item}
    checks = [
        item
        for item in checks
        if isinstance(item, dict)
        and (
            str(item.get("head_sha") or item.get("commit_sha") or "") in commit_set
            or github_client._is_after(  # noqa: SLF001 - consistent cursor semantics
                item.get("completed_at") or item.get("started_at"), since
            )
        )
    ]
    changed = bool(commits or pulls or checks)
    progress = None
    progress_error = None
    if changed:
        try:
            progress = read_repository_text(
                full_name,
                "PROGRESS.md",
                ref=default_branch,
                max_chars=progress_max_chars,
            )
        except GitHubActivityError as exc:
            # PROGRESS.md is helpful context, but missing contents permission must
            # not discard otherwise valid commit/PR/check activity.
            progress_error = str(exc)

    return {
        "repository": metadata,
        "full_name": full_name,
        "default_branch": default_branch,
        "since": since,
        "commits": commits,
        "pull_requests": pulls,
        "check_runs": checks,
        "progress": progress,
        "progress_error": progress_error,
        "source_errors": source_errors,
        "changed": changed,
    }
