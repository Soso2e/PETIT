"""Index existing Obsidian vault Markdown into PETIT's RAG store.

SQLite remains PETIT's structured source of truth. This module treats the user's
existing Obsidian vault as the Markdown brain: read Markdown files, split them
into small chunks, and index those chunks into Chroma under ``petit_vault``.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import chroma_client, config

log = logging.getLogger(__name__)

COLLECTION_NAME = "petit_vault"
EXCLUDED_DIR_NAMES = {".git", ".obsidian", ".trash", "node_modules", "__pycache__"}
MAX_FILE_BYTES = int(os.getenv("PETIT_VAULT_MAX_FILE_BYTES", "1000000"))
MAX_FILES_PER_SYNC = int(os.getenv("PETIT_VAULT_MAX_FILES_PER_SYNC", "2000"))
CHUNK_CHARS = int(os.getenv("PETIT_VAULT_CHUNK_CHARS", "1600"))
CHUNK_OVERLAP = int(os.getenv("PETIT_VAULT_CHUNK_OVERLAP", "160"))
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


def index_configured_vaults(max_files: int | None = None) -> dict[str, Any]:
    """Index configured Obsidian vaults into Chroma.

    Returns lightweight counts and never raises; startup should not fail just
    because embeddings or a vault path are unavailable.
    """
    if not config.OBSIDIAN_VAULT_DIRS:
        return {"configured": False, "vaults": [], "files": 0, "chunks": 0, "failed": 0}

    limit = max_files if max_files is not None else MAX_FILES_PER_SYNC
    files_seen = 0
    chunks_indexed = 0
    failed = 0
    vaults = [str(path) for path in config.OBSIDIAN_VAULT_DIRS]

    for vault_root in config.OBSIDIAN_VAULT_DIRS:
        root = vault_root.expanduser()
        if not root.exists() or not root.is_dir():
            log.debug("Obsidian vault path unavailable: %s", root)
            failed += 1
            continue

        for path in _iter_markdown_files(root):
            if files_seen >= limit:
                return {
                    "configured": True,
                    "vaults": vaults,
                    "files": files_seen,
                    "chunks": chunks_indexed,
                    "failed": failed,
                    "limited": True,
                }
            files_seen += 1
            try:
                chunks_indexed += _index_file(root, path)
            except Exception as exc:  # noqa: BLE001
                log.debug("Vault index skipped %s: %s", path, exc)
                failed += 1

    return {
        "configured": True,
        "vaults": vaults,
        "files": files_seen,
        "chunks": chunks_indexed,
        "failed": failed,
        "limited": False,
    }


def keyword_search(query: str, limit: int = 8) -> list[dict[str, Any]]:
    """Simple fallback search over Markdown when embeddings are unavailable."""
    needle = query.strip().lower()
    if not needle or not config.OBSIDIAN_VAULT_DIRS:
        return []

    results: list[dict[str, Any]] = []
    for root in config.OBSIDIAN_VAULT_DIRS:
        vault_root = root.expanduser()
        if not vault_root.exists() or not vault_root.is_dir():
            continue
        for path in _iter_markdown_files(vault_root):
            text = _read_text(path)
            haystack = text.lower()
            index = haystack.find(needle)
            if index < 0:
                continue
            snippet = _snippet(text, index)
            results.append(
                {
                    "text": snippet,
                    "source_path": str(path),
                    "relative_path": _relative_path(vault_root, path),
                    "heading": _heading_before(text, index),
                    "modified_at": _modified_at(path),
                }
            )
            if len(results) >= limit:
                return results
    return results


def status() -> dict[str, Any]:
    info: dict[str, Any] = {
        "configured": bool(config.OBSIDIAN_VAULT_DIRS),
        "vaults": [str(path) for path in config.OBSIDIAN_VAULT_DIRS],
        "collection": COLLECTION_NAME,
    }
    try:
        info["indexed_chunks"] = chroma_client._collection(COLLECTION_NAME).count()
    except Exception:  # noqa: BLE001
        info["indexed_chunks"] = None
    return info


def _iter_markdown_files(root: Path):
    for path in root.rglob("*.md"):
        if not path.is_file():
            continue
        if any(part in EXCLUDED_DIR_NAMES for part in path.parts):
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        yield path


def _index_file(root: Path, path: Path) -> int:
    text = _read_text(path)
    if not text.strip():
        return 0

    # Remove stale chunks for this file before upserting current chunks.
    chroma_client.delete_where(COLLECTION_NAME, {"source_path": str(path)})

    count = 0
    for chunk_index, (heading, chunk) in enumerate(_chunk_markdown(text)):
        clean = chunk.strip()
        if not clean:
            continue
        ok = chroma_client.add(
            COLLECTION_NAME,
            doc_id=_doc_id(root, path, chunk_index),
            text=clean,
            metadata={
                "source": "obsidian_vault",
                "vault_root": str(root),
                "source_path": str(path),
                "relative_path": _relative_path(root, path),
                "heading": heading,
                "modified_at": _modified_at(path),
                "chunk_index": chunk_index,
                "indexed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
        )
        if ok:
            count += 1
    return count


def _chunk_markdown(text: str) -> list[tuple[str, str]]:
    sections = _sections(text)
    chunks: list[tuple[str, str]] = []
    for heading, section in sections:
        if len(section) <= CHUNK_CHARS:
            chunks.append((heading, section))
            continue
        step = max(CHUNK_CHARS - CHUNK_OVERLAP, 400)
        for start in range(0, len(section), step):
            chunks.append((heading, section[start : start + CHUNK_CHARS]))
    return chunks


def _sections(text: str) -> list[tuple[str, str]]:
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return [("", text)]

    sections: list[tuple[str, str]] = []
    if matches[0].start() > 0:
        sections.append(("", text[: matches[0].start()]))
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        heading = match.group(2).strip()
        sections.append((heading, text[start:end]))
    return sections


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _relative_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return path.name


def _modified_at(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")


def _doc_id(root: Path, path: Path, chunk_index: int) -> str:
    raw = f"{root.resolve()}|{_relative_path(root, path).lower()}|{chunk_index}"
    return "vault_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _snippet(text: str, index: int, radius: int = 360) -> str:
    start = max(index - radius, 0)
    end = min(index + radius, len(text))
    return text[start:end].strip()


def _heading_before(text: str, index: int) -> str:
    heading = ""
    for match in _HEADING_RE.finditer(text[:index]):
        heading = match.group(2).strip()
    return heading
