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
EXCLUDED_DIR_NAMES = {
    ".git", ".obsidian", ".trash", "_attachments", "_private",
    "node_modules", "__pycache__",
}
MAX_FILE_BYTES = int(os.getenv("PETIT_VAULT_MAX_FILE_BYTES", "1000000"))
MAX_FILES_PER_SYNC = int(os.getenv("PETIT_VAULT_MAX_FILES_PER_SYNC", "2000"))
CHUNK_CHARS = int(os.getenv("PETIT_VAULT_CHUNK_CHARS", "1600"))
CHUNK_OVERLAP = int(os.getenv("PETIT_VAULT_CHUNK_OVERLAP", "160"))
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_WORD_RE = re.compile(r"[a-zA-Z0-9_+-]{2,}|[一-龯ぁ-んァ-ヶー]{2,}")
_TEXT_CACHE: dict[str, tuple[int, int, str]] = {}


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
    chunks_skipped = 0
    chunks_deleted = 0
    failed = 0
    vaults = [str(path) for path in config.OBSIDIAN_VAULT_DIRS]

    chunks_deleted += _purge_excluded_chunks()
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
                    "skipped": chunks_skipped,
                    "deleted": chunks_deleted,
                    "failed": failed,
                    "limited": True,
                }
            files_seen += 1
            try:
                file_counts = _index_file(root, path)
                chunks_indexed += file_counts["indexed"]
                chunks_skipped += file_counts["skipped"]
                chunks_deleted += file_counts["deleted"]
            except Exception as exc:  # noqa: BLE001
                log.debug("Vault index skipped %s: %s", path, exc)
                failed += 1

    return {
        "configured": True,
        "vaults": vaults,
        "files": files_seen,
        "chunks": chunks_indexed,
        "skipped": chunks_skipped,
        "deleted": chunks_deleted,
        "failed": failed,
        "limited": False,
    }


def keyword_search(query: str, limit: int = 8) -> list[dict[str, Any]]:
    """Ranked fallback search for natural Japanese queries."""
    tokens = _query_tokens(query)
    if not tokens or not config.OBSIDIAN_VAULT_DIRS:
        return []

    ranked: list[tuple[float, dict[str, Any]]] = []
    for root in config.OBSIDIAN_VAULT_DIRS:
        vault_root = root.expanduser()
        if not vault_root.exists() or not vault_root.is_dir():
            continue
        for path in _iter_markdown_files(vault_root):
            text = _read_text(path)
            relative = _relative_path(vault_root, path)
            haystack = text.casefold()
            path_text = relative.casefold()
            hits = [(token, haystack.find(token)) for token in tokens if token in haystack]
            path_hits = [token for token in tokens if token in path_text]
            if not hits and not path_hits:
                continue
            best_index = min((index for _, index in hits if index >= 0), default=0)
            coverage = len({token for token, _ in hits} | set(path_hits)) / len(tokens)
            score = coverage + len(path_hits) * 0.35 + min(len(hits), 6) * 0.05
            ranked.append((
                score,
                {
                    "text": _snippet(text, best_index),
                    "source_path": str(path),
                    "relative_path": relative,
                    "heading": _heading_before(text, best_index),
                    "modified_at": _modified_at(path),
                    "relevance": round(score, 3),
                },
            ))
    ranked.sort(key=lambda item: (item[0], item[1]["modified_at"]), reverse=True)
    return [item for _, item in ranked[:limit]]


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


def _index_file(root: Path, path: Path) -> dict[str, int]:
    text = _read_text(path)
    if not text.strip():
        deleted = _delete_existing_file_chunks(path)
        return {"indexed": 0, "skipped": 0, "deleted": deleted}

    existing = _existing_file_chunks(path)
    current_ids: set[str] = set()
    docs: list[tuple[str, str, dict[str, Any]]] = []
    skipped = 0
    for chunk_index, (heading, chunk) in enumerate(_chunk_markdown(text)):
        clean = chunk.strip()
        if not clean:
            continue
        doc_id = _doc_id(root, path, chunk_index)
        current_ids.add(doc_id)
        content_hash = _content_hash(clean)
        if existing.get(doc_id, {}).get("content_hash") == content_hash:
            skipped += 1
            continue
        docs.append(
            (
                doc_id,
                clean,
                {
                    "source": "obsidian_vault",
                    "vault_root": str(root),
                    "source_path": str(path),
                    "relative_path": _relative_path(root, path),
                    "heading": heading,
                    "modified_at": _modified_at(path),
                    "chunk_index": chunk_index,
                    "content_hash": content_hash,
                    "indexed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                },
            )
        )

    stale_ids = [doc_id for doc_id in existing if doc_id not in current_ids]
    deleted = len(stale_ids) if chroma_client.delete_ids(COLLECTION_NAME, stale_ids) else 0
    indexed = chroma_client.add_many(COLLECTION_NAME, docs)
    return {"indexed": indexed, "skipped": skipped, "deleted": deleted}


def _existing_file_chunks(path: Path) -> dict[str, dict[str, Any]]:
    try:
        data = chroma_client._collection(COLLECTION_NAME).get(
            where={"source_path": str(path)},
            include=["metadatas"],
        )
    except Exception:  # noqa: BLE001
        return {}
    return {
        str(doc_id): (metadata or {})
        for doc_id, metadata in zip(data.get("ids") or [], data.get("metadatas") or [])
    }


def _delete_existing_file_chunks(path: Path) -> int:
    existing = _existing_file_chunks(path)
    ids = list(existing)
    if chroma_client.delete_ids(COLLECTION_NAME, ids):
        return len(ids)
    return 0


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
    stat = path.stat()
    key = str(path)
    cached = _TEXT_CACHE.get(key)
    signature = (stat.st_mtime_ns, stat.st_size)
    if cached and cached[:2] == signature:
        return cached[2]
    text = path.read_text(encoding="utf-8", errors="replace")
    _TEXT_CACHE[key] = (signature[0], signature[1], text)
    return text


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


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _snippet(text: str, index: int, radius: int = 360) -> str:
    start = max(index - radius, 0)
    end = min(index + radius, len(text))
    return text[start:end].strip()

def _query_tokens(query: str) -> list[str]:
    normalized = " ".join(query.casefold().split())
    tokens: set[str] = set()
    for word in _WORD_RE.findall(normalized):
        tokens.add(word)
        if re.search(r"[一-龯ぁ-んァ-ヶー]", word):
            tokens.update(word[i : i + 2] for i in range(len(word) - 1))
    stop = {"これ", "それ", "どれ", "どう", "って", "です", "ます", "して", "いる", "ある", "こと"}
    return sorted((token for token in tokens if token not in stop), key=len, reverse=True)[:40]


def _purge_excluded_chunks() -> int:
    try:
        data = chroma_client._collection(COLLECTION_NAME).get(include=["metadatas"])
    except Exception:  # noqa: BLE001
        return 0
    excluded = {name.casefold() for name in EXCLUDED_DIR_NAMES}
    stale = []
    for doc_id, metadata in zip(data.get("ids") or [], data.get("metadatas") or []):
        relative = str((metadata or {}).get("relative_path", ""))
        if any(part.casefold() in excluded for part in Path(relative).parts):
            stale.append(doc_id)
    if stale:
        chroma_client.delete_ids(COLLECTION_NAME, stale)
    return len(stale)




def _heading_before(text: str, index: int) -> str:
    heading = ""
    for match in _HEADING_RE.finditer(text[:index]):
        heading = match.group(2).strip()
    return heading
