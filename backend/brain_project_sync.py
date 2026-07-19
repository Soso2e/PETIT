"""Confirmation-first project mapping for safe Obsidian/BRAIN Markdown notes.

Markdown remains canonical. PETIT stores only bounded project-scoped cache data,
confirmation candidates, freshness, and idempotent note-update events.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from . import config, db, project_completion, project_continuity, vault_indexer

_PROVIDER = "brain"
_MAX_EXCERPT_CHARS = max(200, int(os.getenv("PETIT_BRAIN_PROJECT_EXCERPT_CHARS", "1200")))
_MAX_HEADINGS = max(1, int(os.getenv("PETIT_BRAIN_PROJECT_MAX_HEADINGS", "12")))
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS brain_note_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id TEXT NOT NULL UNIQUE,
    vault_index INTEGER NOT NULL,
    relative_path TEXT NOT NULL,
    title TEXT NOT NULL,
    snippet TEXT,
    match_reason TEXT,
    source_modified_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    suggested_project_ids TEXT NOT NULL DEFAULT '[]',
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_brain_note_candidates_status
ON brain_note_candidates(status, updated_at);

CREATE TABLE IF NOT EXISTS brain_project_notes_cache (
    external_id TEXT PRIMARY KEY,
    internal_project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
    vault_index INTEGER NOT NULL,
    relative_path TEXT NOT NULL,
    title TEXT NOT NULL,
    excerpt TEXT NOT NULL,
    headings_json TEXT NOT NULL DEFAULT '[]',
    content_hash TEXT NOT NULL,
    source_modified_at TEXT,
    source_size INTEGER,
    synced_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_brain_project_notes_project
ON brain_project_notes_cache(internal_project_id, source_modified_at);
"""


def ensure_brain_project_schema() -> None:
    project_completion.ensure_completion_schema()
    with db.get_connection() as conn:
        conn.executescript(_SCHEMA)


def _external_id(vault_index: int, relative_path: str) -> str:
    return f"vault:{vault_index}:{Path(relative_path).as_posix()}"


def parse_external_id(external_id: str) -> tuple[int, str]:
    prefix, separator, remainder = str(external_id).partition(":")
    if prefix != "vault" or not separator:
        raise ValueError("invalid BRAIN note external id")
    index_text, separator, relative_path = remainder.partition(":")
    if not separator or not index_text.isdigit() or not relative_path:
        raise ValueError("invalid BRAIN note external id")
    return int(index_text), relative_path


def resolve_note(vault_index: int, relative_path: str, *, require_exists: bool = True) -> tuple[Path, Path]:
    if not config.OBSIDIAN_VAULT_DIRS:
        raise ValueError("PETIT_OBSIDIAN_VAULT_DIRSが設定されていません。")
    if vault_index < 0 or vault_index >= len(config.OBSIDIAN_VAULT_DIRS):
        raise ValueError("vault_indexが設定済みVaultの範囲外です。")
    raw = Path(relative_path)
    excluded = {name.casefold() for name in vault_indexer.EXCLUDED_DIR_NAMES}
    if raw.is_absolute() or ".." in raw.parts or raw.suffix.casefold() != ".md":
        raise ValueError("Vault内の相対Markdownパスだけを指定できます。")
    if any(part.casefold() in excluded for part in raw.parts):
        raise ValueError("除外フォルダ内のノートは対象にできません。")
    root = config.OBSIDIAN_VAULT_DIRS[vault_index].expanduser().resolve()
    target = (root / raw).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("Vault外のパスは対象にできません。") from exc
    if require_exists:
        if not target.exists() or not target.is_file():
            raise FileNotFoundError("対象BRAINノートが見つかりません。")
        if target.stat().st_size > vault_indexer.MAX_FILE_BYTES:
            raise ValueError("BRAINノートがサイズ上限を超えています。")
    return root, target


def _note_data(vault_index: int, relative_path: str) -> dict[str, Any]:
    root, target = resolve_note(vault_index, relative_path)
    text = target.read_text(encoding="utf-8", errors="replace")
    stat = target.stat()
    headings = [match.group(2).strip() for match in _HEADING_RE.finditer(text)][:_MAX_HEADINGS]
    title = headings[0] if headings else target.stem
    body_lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#") and line.strip() != "---"
    ]
    body = "\n".join(body_lines)
    excerpt = body[:_MAX_EXCERPT_CHARS].strip() or text[:_MAX_EXCERPT_CHARS].strip()
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return {
        "external_id": _external_id(vault_index, str(target.relative_to(root))),
        "vault_index": vault_index,
        "relative_path": str(target.relative_to(root)),
        "title": title,
        "excerpt": excerpt,
        "snippet": excerpt[:360],
        "headings": headings,
        "content_hash": content_hash,
        "source_modified_at": vault_indexer._modified_at(target),
        "source_size": stat.st_size,
    }


def _vault_index_for_path(source_path: str) -> tuple[int, str]:
    target = Path(source_path).resolve()
    for index, configured_root in enumerate(config.OBSIDIAN_VAULT_DIRS):
        root = configured_root.expanduser().resolve()
        try:
            relative = target.relative_to(root)
        except ValueError:
            continue
        resolve_note(index, str(relative))
        return index, str(relative)
    raise ValueError("Vault外のパスは候補にできません。")


def _candidate_row(row: Any) -> dict[str, Any]:
    item = dict(row)
    for key, fallback in (("metadata_json", {}), ("suggested_project_ids", [])):
        raw = item.pop(key)
        try:
            item[key.removesuffix("_json")] = json.loads(str(raw or ""))
        except json.JSONDecodeError:
            item[key.removesuffix("_json")] = fallback
    return item


def _upsert_candidate(note: dict[str, Any], *, suggested_project_ids: list[str], match_reason: str) -> dict[str, Any]:
    ensure_brain_project_schema()
    now = db.now_iso()
    suggestions = list(dict.fromkeys(str(item) for item in suggested_project_ids if str(item).strip()))
    metadata = {
        "headings": note.get("headings") or [],
        "content_hash": note.get("content_hash"),
        "source_size": note.get("source_size"),
    }
    with db.get_connection() as conn:
        linked = conn.execute(
            "SELECT project_id FROM project_source_links WHERE provider='brain' AND external_id=? "
            "AND status='active' AND confirmed_at IS NOT NULL",
            (note["external_id"],),
        ).fetchone()
        project_id = str(linked["project_id"]) if linked else None
        conn.execute(
            "INSERT INTO brain_note_candidates "
            "(external_id, vault_index, relative_path, title, snippet, match_reason, source_modified_at, "
            "metadata_json, suggested_project_ids, project_id, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(external_id) DO UPDATE SET vault_index=excluded.vault_index, relative_path=excluded.relative_path, "
            "title=excluded.title, snippet=excluded.snippet, match_reason=excluded.match_reason, "
            "source_modified_at=excluded.source_modified_at, metadata_json=excluded.metadata_json, "
            "suggested_project_ids=excluded.suggested_project_ids, project_id=excluded.project_id, "
            "status=CASE WHEN brain_note_candidates.status='ignored' AND excluded.project_id IS NULL "
            "THEN 'ignored' ELSE excluded.status END, updated_at=excluded.updated_at",
            (
                note["external_id"],
                note["vault_index"],
                note["relative_path"],
                note["title"],
                note.get("snippet"),
                match_reason,
                note.get("source_modified_at"),
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                json.dumps([] if project_id else suggestions, ensure_ascii=False),
                project_id,
                "linked" if project_id else "pending",
                now,
                now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM brain_note_candidates WHERE external_id=?",
            (note["external_id"],),
        ).fetchone()
    return _candidate_row(row) if row else {}


def inspect_note(relative_path: str, *, vault_index: int = 0, project_id: str | None = None) -> dict[str, Any]:
    if project_id and not project_continuity.get_project(project_id):
        return {"ok": False, "error": "project not found"}
    try:
        note = _note_data(vault_index, relative_path)
        candidate = _upsert_candidate(
            note,
            suggested_project_ids=[project_id] if project_id else [],
            match_reason="explicit_path",
        )
        return {"ok": True, "candidate": candidate}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}


def _project_search_terms(project_id: str) -> list[str]:
    project = project_continuity.get_project(project_id)
    if not project:
        raise ValueError("project not found")
    terms = [str(project["name"])]
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT alias FROM project_aliases WHERE project_id=? ORDER BY created_at, normalized_alias",
            (project_id,),
        ).fetchall()
    terms.extend(str(row["alias"]) for row in rows)
    return list(dict.fromkeys(term.strip() for term in terms if term.strip()))


def discover_project_candidates(project_id: str, limit: int = 10) -> dict[str, Any]:
    try:
        terms = _project_search_terms(project_id)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "candidates": []}
    if not config.OBSIDIAN_VAULT_DIRS:
        return {"ok": False, "configured": False, "error": "BRAIN vaultが設定されていません", "candidates": []}
    found: dict[str, dict[str, Any]] = {}
    for term in terms:
        for result in vault_indexer.keyword_search(term, limit=max(1, min(limit, 20))):
            try:
                vault_index, relative_path = _vault_index_for_path(str(result.get("source_path") or ""))
                note = _note_data(vault_index, relative_path)
            except Exception:
                continue
            note["snippet"] = str(result.get("text") or note.get("snippet") or "")[:360]
            candidate = _upsert_candidate(
                note,
                suggested_project_ids=[project_id],
                match_reason=f"project_term:{term}",
            )
            found[str(candidate["external_id"])] = candidate
            if len(found) >= max(1, min(limit, 50)):
                break
        if len(found) >= max(1, min(limit, 50)):
            break
    return {
        "ok": True,
        "configured": True,
        "project_id": project_id,
        "terms": terms,
        "count": len(found),
        "candidates": list(found.values()),
    }


def list_candidates(status: str = "pending", limit: int = 20) -> list[dict[str, Any]]:
    ensure_brain_project_schema()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM brain_note_candidates WHERE status=? ORDER BY updated_at DESC LIMIT ?",
            (status, max(1, min(limit, 100))),
        ).fetchall()
    return [_candidate_row(row) for row in rows]


def get_candidate(candidate_id: int) -> dict[str, Any] | None:
    ensure_brain_project_schema()
    with db.get_connection() as conn:
        row = conn.execute("SELECT * FROM brain_note_candidates WHERE id=?", (candidate_id,)).fetchone()
    return _candidate_row(row) if row else None


def _source_key(external_id: str) -> str:
    return "brain:note:" + hashlib.sha1(external_id.encode("utf-8")).hexdigest()


def _insert_update_event(
    conn: Any,
    *,
    project_id: str,
    note: dict[str, Any],
) -> None:
    now = db.now_iso()
    idempotency_key = hashlib.sha256(
        f"brain|{note['external_id']}|{note['content_hash']}".encode("utf-8")
    ).hexdigest()
    payload = {
        "external_id": note["external_id"],
        "relative_path": note["relative_path"],
        "title": note["title"],
        "headings": note["headings"],
        "content_hash": note["content_hash"],
        "source_modified_at": note["source_modified_at"],
    }
    conn.execute(
        "INSERT OR IGNORE INTO project_events "
        "(project_id, provider, event_type, summary, payload_json, idempotency_key, occurred_at, created_at) "
        "VALUES (?, 'brain', 'brain_note_updated', ?, ?, ?, ?, ?)",
        (
            project_id,
            f"BRAINノート「{note['title']}」が更新された",
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            idempotency_key,
            note.get("source_modified_at") or now,
            now,
        ),
    )


def refresh_note_link(project_id: str, external_id: str, *, force: bool = False) -> dict[str, Any]:
    ensure_brain_project_schema()
    source = _source_key(external_id)
    try:
        vault_index, relative_path = parse_external_id(external_id)
        _, target = resolve_note(vault_index, relative_path)
        stat = target.stat()
        with db.get_connection() as conn:
            cached = conn.execute(
                "SELECT content_hash, source_modified_at, source_size FROM brain_project_notes_cache "
                "WHERE external_id=? AND internal_project_id=?",
                (external_id, project_id),
            ).fetchone()
        if cached and not force and int(cached["source_size"] or -1) == stat.st_size:
            current_modified = vault_indexer._modified_at(target)
            state = db.sync_state(source)
            if str(cached["source_modified_at"] or "") == current_modified and not state.get("last_failure_at"):
                return {
                    "provider": "brain",
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
        note = _note_data(vault_index, relative_path)
        now = db.now_iso()
        previous_hash = str(cached["content_hash"]) if cached else None
        changed = bool(previous_hash and previous_hash != note["content_hash"])
        with db.get_connection() as conn:
            conn.execute(
                "INSERT INTO brain_project_notes_cache "
                "(external_id, internal_project_id, vault_index, relative_path, title, excerpt, headings_json, "
                "content_hash, source_modified_at, source_size, synced_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(external_id) DO UPDATE SET internal_project_id=excluded.internal_project_id, "
                "vault_index=excluded.vault_index, relative_path=excluded.relative_path, title=excluded.title, "
                "excerpt=excluded.excerpt, headings_json=excluded.headings_json, content_hash=excluded.content_hash, "
                "source_modified_at=excluded.source_modified_at, source_size=excluded.source_size, synced_at=excluded.synced_at",
                (
                    external_id,
                    project_id,
                    note["vault_index"],
                    note["relative_path"],
                    note["title"],
                    note["excerpt"],
                    json.dumps(note["headings"], ensure_ascii=False),
                    note["content_hash"],
                    note["source_modified_at"],
                    note["source_size"],
                    now,
                ),
            )
            if changed:
                _insert_update_event(conn, project_id=project_id, note=note)
        synced_at = db.record_sync_success(source, 1 if changed else 0)
        return {
            "provider": "brain",
            "source": source,
            "external_id": external_id,
            "ok": True,
            "configured": True,
            "skipped": False,
            "cached": False,
            "stale": False,
            "changed": changed,
            "last_synced_at": synced_at,
            "error": None,
            "note": {key: note[key] for key in ("title", "relative_path", "headings", "source_modified_at")},
        }
    except Exception as exc:
        error = str(exc)[:300]
        db.record_sync_failure(source, error)
        state = db.sync_state(source)
        with db.get_connection() as conn:
            cached = conn.execute(
                "SELECT 1 FROM brain_project_notes_cache WHERE external_id=? AND internal_project_id=?",
                (external_id, project_id),
            ).fetchone()
        return {
            "provider": "brain",
            "source": source,
            "external_id": external_id,
            "ok": False,
            "configured": bool(config.OBSIDIAN_VAULT_DIRS),
            "skipped": False,
            "cached": bool(cached),
            "stale": bool(cached),
            "last_synced_at": state.get("last_success_at"),
            "error": error,
        }


def link_candidate(candidate_id: int, project_id: str) -> dict[str, Any]:
    candidate = get_candidate(candidate_id)
    if not candidate:
        raise ValueError("BRAIN note candidate not found")
    if candidate["status"] == "ignored":
        raise ValueError("ignored BRAIN note candidate must be re-discovered before linking")
    if not project_continuity.get_project(project_id):
        raise ValueError("project not found")
    note = _note_data(int(candidate["vault_index"]), str(candidate["relative_path"]))
    link = project_continuity.link_project_source(
        project_id,
        "brain",
        str(candidate["external_id"]),
        metadata={
            "vault_index": candidate["vault_index"],
            "relative_path": candidate["relative_path"],
            "title": candidate["title"],
            "source_modified_at": note["source_modified_at"],
        },
        confirmed=True,
    )
    now = db.now_iso()
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE brain_note_candidates SET project_id=?, status='linked', updated_at=? WHERE id=?",
            (project_id, now, candidate_id),
        )
    refreshed = refresh_note_link(project_id, str(candidate["external_id"]), force=True)
    return {"linked": True, "candidate": get_candidate(candidate_id), "source_link": link, "refresh": refreshed}


def ignore_candidate(candidate_id: int) -> dict[str, Any]:
    candidate = get_candidate(candidate_id)
    if not candidate:
        raise ValueError("BRAIN note candidate not found")
    now = db.now_iso()
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE brain_note_candidates SET status='ignored', project_id=NULL, updated_at=? WHERE id=?",
            (now, candidate_id),
        )
    return {"ignored": True, "candidate": get_candidate(candidate_id)}


def project_notes(project_id: str, limit: int = 3) -> list[dict[str, Any]]:
    ensure_brain_project_schema()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT external_id, vault_index, relative_path, title, excerpt, headings_json, content_hash, "
            "source_modified_at, synced_at FROM brain_project_notes_cache WHERE internal_project_id=? "
            "ORDER BY source_modified_at DESC, title LIMIT ?",
            (project_id, max(1, min(limit, 10))),
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            item["headings"] = json.loads(str(item.pop("headings_json") or "[]"))
        except json.JSONDecodeError:
            item["headings"] = []
        item["excerpt"] = str(item.get("excerpt") or "")[:_MAX_EXCERPT_CHARS]
        result.append(item)
    return result
