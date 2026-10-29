"""Best-effort refresh of confirmed external sources before project resume.

Only source links explicitly confirmed for the selected internal project are used.
Failures never block checkpoint-based resume; they are returned for observability and
rendered as a saved-cache warning by ``project_resume``.
"""
from __future__ import annotations

from typing import Any, Callable

from . import (
    brain_project_sync,
    db,
    github_sync,
    notion_project_sync,
    project_continuity,
)


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
    github_refresher: Callable[..., dict[str, Any]] | None = None,
    brain_refresher: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Refresh confirmed sources for only the selected internal project."""
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
            elif provider == "github":
                refresh = github_refresher or github_sync.refresh_repository_link
                result = _provider_result(
                    "github",
                    [
                        refresh(project_id, str(link["external_id"]), force=force)
                        for link in grouped[provider]
                    ],
                )
            elif provider == "brain":
                refresh = brain_refresher or brain_project_sync.refresh_note_link
                result = _provider_result(
                    "brain",
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
