"""Best-effort refresh of confirmed external sources before project resume.

Only source links explicitly confirmed for the selected internal project are used.
Failures never block checkpoint-based resume; they are returned for observability and
rendered as a saved-cache warning by ``project_resume``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from . import (
    db,
    github_sync,
    linkraft_config,
    linkraft_sync,
    notion_project_sync,
    project_continuity,
)
from .linkraft_client import LinkraftError, get_project_snapshot


def confirmed_source_links(project_id: str) -> list[dict[str, Any]]:
    """Return active, user-confirmed source links for one internal project."""
    project_continuity.ensure_project_schema()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT id, provider, external_id, external_url, confirmed_at, metadata_json "
            "FROM project_source_links WHERE project_id=? AND status='active' "
            "AND confirmed_at IS NOT NULL ORDER BY provider, external_id",
            (project_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _fresh_enough(source: str, ttl_seconds: float) -> bool:
    state = db.sync_state(source)
    success = _parse_time(state.get("last_success_at"))
    failure = _parse_time(state.get("last_failure_at"))
    if success is None or (failure is not None and failure >= success):
        return False
    age = (datetime.now(timezone.utc) - success).total_seconds()
    return age < max(0.0, ttl_seconds)


def _record_linkraft_failure(external_id: str, error: str) -> None:
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO linkraft_sync_cursors (external_project_id, last_failure_at, last_error) "
            "VALUES (?, ?, ?) ON CONFLICT(external_project_id) DO UPDATE SET "
            "last_failure_at=excluded.last_failure_at, last_error=excluded.last_error",
            (external_id, db.now_iso(), error),
        )


def refresh_linkraft_link(
    project_id: str,
    external_id: str,
    *,
    force: bool = False,
    snapshot_loader: Callable[[str, str | None], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Refresh one confirmed Linkraft project without touching other linked projects."""
    source = f"linkraft:project:{external_id}"
    if snapshot_loader is None and not linkraft_config.configured():
        return {
            "provider": "linkraft",
            "source": source,
            "external_id": external_id,
            "ok": False,
            "configured": False,
            "skipped": True,
            "stale": bool(db.sync_state(source).get("last_success_at")),
            "error": "未設定",
        }
    if not force and _fresh_enough(source, linkraft_config.SYNC_TTL_SECONDS):
        state = db.sync_state(source)
        return {
            "provider": "linkraft",
            "source": source,
            "external_id": external_id,
            "ok": True,
            "configured": True,
            "skipped": False,
            "cached": True,
            "stale": False,
            "last_synced_at": state.get("last_success_at"),
            "error": None,
        }

    loader = snapshot_loader or get_project_snapshot
    try:
        snapshot = loader(external_id, linkraft_sync._cursor(external_id))
        applied = linkraft_sync.apply_snapshot(snapshot, project_id)
        count = sum(int(value) for value in applied.get("counts", {}).values())
        synced_at = db.record_sync_success(source, count)
        return {
            "provider": "linkraft",
            "source": source,
            "external_id": external_id,
            "ok": True,
            "configured": True,
            "skipped": False,
            "cached": False,
            "stale": False,
            "last_synced_at": synced_at,
            "error": None,
            "result": applied,
        }
    except Exception as exc:  # LinkraftError plus defensive adapter boundary.
        error = linkraft_sync._safe_error(exc if isinstance(exc, Exception) else LinkraftError(str(exc)))
        db.record_sync_failure(source, error)
        _record_linkraft_failure(external_id, error)
        state = db.sync_state(source)
        return {
            "provider": "linkraft",
            "source": source,
            "external_id": external_id,
            "ok": False,
            "configured": True,
            "skipped": False,
            "cached": bool(state.get("last_success_at")),
            "stale": bool(state.get("last_success_at")),
            "last_synced_at": state.get("last_success_at"),
            "error": error,
        }


def _refresh_notion(*, force: bool) -> dict[str, Any]:
    result = notion_project_sync.sync_all_if_configured(force=force)
    if not result.get("configured"):
        return result | {"provider": "notion", "skipped": True}
    return result | {"provider": "notion", "skipped": False}


def _provider_result(provider: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    active = [item for item in items if not item.get("skipped")]
    return {
        "provider": provider,
        "ok": bool(active) and all(item.get("ok") for item in active),
        "configured": any(item.get("configured") for item in items),
        "skipped": not active,
        "stale": any(item.get("stale") for item in items),
        "error": "; ".join(str(item["error"]) for item in items if item.get("error")) or None,
        "links": items,
    }


def refresh_project_sources(
    project_id: str,
    *,
    force: bool = False,
    notion_refresher: Callable[..., dict[str, Any]] | None = None,
    linkraft_refresher: Callable[..., dict[str, Any]] | None = None,
    github_refresher: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Refresh each confirmed provider at most once for the selected project.

    Linkraft and GitHub may have multiple confirmed external IDs for a project, but
    no other project's source link is read. Unsupported providers are skipped.
    """
    if not project_continuity.get_project(project_id):
        return {
            "ok": False,
            "project_id": project_id,
            "providers": {},
            "attempted": [],
            "failed": [],
            "skipped": [],
            "error": "project not found",
        }

    links = confirmed_source_links(project_id)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for link in links:
        grouped.setdefault(str(link["provider"]), []).append(link)

    providers: dict[str, dict[str, Any]] = {}
    attempted: list[str] = []
    failed: list[str] = []
    skipped: list[str] = []

    for provider in sorted(grouped):
        try:
            if provider == "notion":
                refresh = notion_refresher or _refresh_notion
                result = refresh(force=force)
            elif provider == "linkraft":
                refresh = linkraft_refresher or refresh_linkraft_link
                result = _provider_result(
                    "linkraft",
                    [
                        refresh(project_id, str(link["external_id"]), force=force)
                        for link in grouped[provider]
                    ],
                )
            elif provider == "github":
                refresh = github_refresher or github_sync.refresh_repository_link
                result = _provider_result(
                    "github",
                    [
                        refresh(project_id, str(link["external_id"]), force=force)
                        for link in grouped[provider]
                    ],
                )
            else:
                result = {
                    "provider": provider,
                    "ok": False,
                    "configured": False,
                    "skipped": True,
                    "stale": False,
                    "error": "unsupported provider",
                }
        except Exception as exc:  # Never block project resume.
            result = {
                "provider": provider,
                "ok": False,
                "configured": True,
                "skipped": False,
                "stale": False,
                "error": str(exc)[:300],
            }

        providers[provider] = result
        if result.get("skipped"):
            skipped.append(provider)
        else:
            attempted.append(provider)
            if not result.get("ok"):
                failed.append(provider)

    return {
        "ok": not failed,
        "project_id": project_id,
        "providers": providers,
        "attempted": attempted,
        "failed": failed,
        "skipped": skipped,
        "confirmed_link_count": len(links),
        "error": "; ".join(
            f"{provider}: {providers[provider].get('error')}" for provider in failed
        ) or None,
    }
