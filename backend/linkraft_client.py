"""HTTP client for Linkraft's owner-scoped PETIT read API."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import httpx

from . import linkraft_config


class LinkraftError(RuntimeError):
    """Raised when the Linkraft integration is unavailable or returns invalid data."""


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {linkraft_config.READ_TOKEN}",
        "Accept": "application/json",
    }


def _get(path: str, query: dict[str, str] | None = None, timeout: float = 20) -> dict[str, Any]:
    if not linkraft_config.configured():
        raise LinkraftError("Linkraft integration is not configured")
    suffix = f"?{urlencode(query)}" if query else ""
    url = f"{linkraft_config.BASE_URL}{path}{suffix}"
    try:
        response = httpx.get(url, headers=_headers(), timeout=timeout)
        response.raise_for_status()
        data = response.json()
    except httpx.ConnectError as exc:
        raise LinkraftError("Linkraftへ接続できませんでした。") from exc
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:300]
        raise LinkraftError(f"Linkraft API error {exc.response.status_code}: {body}") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise LinkraftError(f"Linkraftとの通信または応答解析に失敗しました: {exc}") from exc
    if not isinstance(data, dict):
        raise LinkraftError("Linkraft API returned an invalid response")
    return data


def list_owned_projects() -> list[dict[str, Any]]:
    data = _get("/api/integrations/petit/projects")
    projects = data.get("projects") or []
    if not isinstance(projects, list):
        raise LinkraftError("Linkraft project list is invalid")
    return [item for item in projects if isinstance(item, dict)]


def get_project_snapshot(project_id: str, since: str | None = None) -> dict[str, Any]:
    query = {"projectId": project_id}
    if since:
        query["since"] = since
    data = _get("/api/integrations/petit/snapshot", query=query)
    if str((data.get("project") or {}).get("id") or "") != project_id:
        raise LinkraftError("Linkraft snapshot project identity mismatch")
    return data
