"""Confirmed Project Continuity links to already allowlisted local repositories."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from . import config, db, local_development, project_continuity, project_source_links, workspace_context

PROVIDER = "local_workspace"


def _safe_root(path: Path) -> Path:
    lexical = path.expanduser().absolute()
    if "_private" in {p.casefold() for p in lexical.parts}:
        raise ValueError("private_workspace_is_not_allowed")
    for part in (lexical, *lexical.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ValueError("linked_workspace_path_is_not_allowed")
    root = lexical.resolve(strict=True)
    if not root.is_dir() or "_private" in {p.casefold() for p in root.parts}:
        raise ValueError("invalid_workspace")
    return root


def allowed_roots() -> list[Path]:
    if not config.WORKSPACE_CONTEXT_ENABLED or not config.WORKSPACE_LOCAL_DEVELOPMENT_ENABLED:
        return []
    result = []
    for configured in config.WORKSPACE_CONTEXT_DIRS:
        try:
            root = _safe_root(configured)
            if root not in result:
                result.append(root)
        except (OSError, ValueError):
            continue
    return result


def validate_root(path: str) -> Path:
    root = _safe_root(Path(path))
    if root not in allowed_roots():
        raise ValueError("workspace_must_be_an_explicitly_allowlisted_root")
    return root


def links(project_id: str) -> list[dict]:
    project_continuity.ensure_project_schema()
    if project_continuity.get_project(project_id) is None:
        raise ValueError("project_not_found")
    with db.get_connection() as connection:
        ids = [row[0] for row in connection.execute(
            "SELECT id FROM project_source_links WHERE project_id=? AND provider=? AND status='active' "
            "AND confirmed_at IS NOT NULL ORDER BY id", (project_id, PROVIDER))]
    return [project_continuity.get_project_source_link(link_id) for link_id in ids]


def list_workspaces(project_id: str | None = None) -> dict:
    roots = allowed_roots()
    return {"enabled": bool(roots), "available": [
        {"path": str(root), "name": root.name, "workspace_id": local_development.workspace_identity(root)}
        for root in roots], "project_id": project_id,
        "confirmed_links": links(project_id) if project_id else [],
        "mapping_rule": "confirmed_project_id_and_exact_allowlisted_path_only"}


def link(project_id: str, path: str) -> dict:
    root = validate_root(path)
    try:
        actual = workspace_context._command([
            "git", "-c", "core.fsmonitor=false", "-C", str(root), "rev-parse", "--show-toplevel"
        ]).decode("utf-8").strip()
        valid = Path(actual).resolve(strict=True) == root
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError):
        valid = False
    if not valid:
        raise ValueError("workspace_is_not_an_observable_repository_root")
    project = project_continuity.get_project(project_id)
    if project is None:
        raise ValueError("project_not_found")
    external_id = os.path.normcase(str(root))
    metadata = {"path": str(root), "name": root.name,
                "workspace_id": local_development.workspace_identity(root)}
    previous = project_source_links.source_link_history(PROVIDER, external_id)
    if previous and previous["project_id"] != project_id and previous["status"] == "removed":
        saved = project_source_links.reassign_removed_source_link(
            previous["id"], project_id, metadata=metadata, confirmed=True)
    else:
        saved = project_continuity.link_project_source(
            project_id, PROVIDER, external_id, metadata=metadata, confirmed=True)
    return {"linked": True, "project": {"id": project_id, "name": project["name"]}, "source_link": saved}


def unlink(project_id: str, link_id: int) -> dict:
    saved = project_continuity.get_project_source_link(link_id)
    if not saved or saved["project_id"] != project_id or saved["provider"] != PROVIDER:
        raise ValueError("project_workspace_link_not_found")
    # Removing a mapping never moves/deletes the repository. Missing paths can
    # still be unlinked, and the tombstone is retained for explicit reassignment.
    return {"unlinked": True, "source_link": project_continuity.remove_project_source_link(link_id)}


def status(project_id: str) -> dict:
    confirmed = links(project_id)
    if not confirmed:
        return {"ok": False, "status": "project_workspace_not_linked", "project_id": project_id}
    snapshot = workspace_context.get_workspace_context()
    if snapshot.get("status") != "observed" or snapshot.get("stale"):
        return {"ok": False, "status": "stale_or_pending", "project_id": project_id,
                "collected_at": snapshot.get("collected_at"), "stale": True}
    observations = {item.get("workspace_id"): item for item in snapshot.get("workspaces", [])}
    workspaces = []
    for saved in confirmed:
        metadata = saved["metadata"]
        try:
            root = validate_root(metadata["path"])
            identity = local_development.workspace_identity(root)
            if identity != metadata["workspace_id"]:
                raise ValueError("workspace_identity_changed")
            observed = observations.get(identity)
            workspaces.append({"link_id": saved["id"], "confirmed_at": saved["confirmed_at"],
                               "status": observed.get("status") if observed else "not_in_observation_cache",
                               "workspace": observed})
        except (OSError, ValueError, KeyError):
            workspaces.append({"link_id": saved["id"], "status": "unavailable_or_no_longer_allowlisted"})
    return {"ok": all(w["status"] == "ok" for w in workspaces), "project_id": project_id,
            "status": "observed", "collected_at": snapshot["collected_at"], "stale": False,
            "workspaces": workspaces, "source_boundary": "local_checkout_no_fetch_docs_are_unverified"}
