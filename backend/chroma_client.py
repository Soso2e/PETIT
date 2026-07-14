"""ChromaDB vector store client for PETIT RAG search.

Design:
- Persistent store at storage/chroma/
- Embeddings via LM Studio /v1/embeddings (custom EmbeddingFunction)
- If LM Studio is unreachable, all operations return None and callers
  fall back to SQLite LIKE search — server never crashes.
- Two collections:
    petit_memory       : items saved via save_memory
    petit_conversations: past conversation turns
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
import time
import threading
from collections import OrderedDict
from typing import Any

import chromadb
import httpx
from chromadb import EmbeddingFunction, Embeddings

from . import config

log = logging.getLogger(__name__)


@dataclass
class EmbeddingStats:
    requests: int = 0
    inputs: int = 0
    last_elapsed_ms: int | None = None


_embedding_stats = EmbeddingStats()

# ---------------------------------------------------------------------------
# Custom embedding function — calls LM Studio /v1/embeddings
# ---------------------------------------------------------------------------

class LMStudioEmbeddingFunction(EmbeddingFunction):
    """Thin wrapper around LM Studio's OpenAI-compatible embeddings endpoint."""

    def __call__(self, input: list[str]) -> Embeddings:  # type: ignore[override]
        # Serialize cache misses so concurrent identical requests share one call.
        with _embedding_lock:
            cached = [_embedding_cache.get(text) for text in input]
            missing = list(dict.fromkeys(text for text, value in zip(input, cached) if value is None))
            if not missing:
                return [value for value in cached if value is not None]
            url = f"{config.EMBED_BASE_URL.rstrip('/')}/embeddings"
            payload = {"model": config.EMBED_MODEL, "input": missing}
            headers = {"Authorization": f"Bearer {config.LM_API_KEY}"}
            start = time.monotonic()
            resp = httpx.post(url, json=payload, headers=headers, timeout=config.EMBED_TIMEOUT)
            resp.raise_for_status()
            _embedding_stats.requests += 1
            _embedding_stats.inputs += len(missing)
            _embedding_stats.last_elapsed_ms = max(0, round((time.monotonic() - start) * 1000))
            data = resp.json()
            # OpenAI format: {"data": [{"index": 0, "embedding": [...]}, ...]}
            for item in sorted(data["data"], key=lambda x: x["index"]):
                text = missing[item["index"]]
                _embedding_cache[text] = item["embedding"]
                _embedding_cache.move_to_end(text)
            while len(_embedding_cache) > _EMBEDDING_CACHE_SIZE:
                _embedding_cache.popitem(last=False)
            return [_embedding_cache[text] for text in input]


_embedding_fn = LMStudioEmbeddingFunction()
_embedding_cache: OrderedDict[str, list[float]] = OrderedDict()
_embedding_lock = threading.Lock()
_EMBEDDING_CACHE_SIZE = 128

# ---------------------------------------------------------------------------
# Client & collections (lazy init)
# ---------------------------------------------------------------------------

_client: chromadb.ClientAPI | None = None
_embedding_unavailable_until = 0.0


def _get_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        config.CHROMA_PATH.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(config.CHROMA_PATH))
    return _client


def _collection(name: str) -> chromadb.Collection:
    return _get_client().get_or_create_collection(
        name=name,
        embedding_function=_embedding_fn,
        metadata={"hnsw:space": "cosine"},
    )


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def _embedding_available() -> bool:
    return time.monotonic() >= _embedding_unavailable_until


def _mark_embedding_unavailable() -> None:
    global _embedding_unavailable_until
    _embedding_unavailable_until = time.monotonic() + config.EMBED_RETRY_SECONDS


def add(collection_name: str, doc_id: str, text: str, metadata: dict[str, Any] | None = None) -> bool:
    """Embed and upsert a single document. Returns False on any error (LLM down etc.)."""
    return add_many(collection_name, [(doc_id, text, metadata or {})]) == 1


def add_many(collection_name: str, docs: list[tuple[str, str, dict[str, Any]]]) -> int:
    """Embed and upsert documents in one Chroma call. Returns indexed count."""
    if not _embedding_available():
        return 0
    if not docs:
        return 0
    try:
        col = _collection(collection_name)
        col.upsert(
            ids=[doc_id for doc_id, _, _ in docs],
            documents=[text for _, text, _ in docs],
            metadatas=[metadata for _, _, metadata in docs],
        )
        return len(docs)
    except Exception as exc:  # noqa: BLE001
        log.debug("Chroma add failed (%s): %s", collection_name, exc)
        _mark_embedding_unavailable()
        return 0


def delete_where(collection_name: str, where: dict[str, Any]) -> bool:
    """Delete documents matching metadata filters. Returns False on any error."""
    try:
        col = _collection(collection_name)
        col.delete(where=where)
        return True
    except Exception as exc:  # noqa: BLE001
        log.debug("Chroma delete failed (%s): %s", collection_name, exc)
        return False

def delete_ids(collection_name: str, ids: list[str]) -> bool:
    """Delete documents by id. Empty input is a successful no-op."""
    if not ids:
        return True
    try:
        _collection(collection_name).delete(ids=ids)
        return True
    except Exception as exc:  # noqa: BLE001
        log.debug("Chroma delete ids failed (%s): %s", collection_name, exc)
        return False


def query(
    collection_name: str,
    text: str,
    n_results: int = 5,
) -> list[dict[str, Any]] | None:
    """Semantic search. Returns None if unavailable (caller uses LIKE fallback).

    Each result: {id, document, distance, metadata}
    """
    if not _embedding_available():
        return None
    try:
        col = _collection(collection_name)
        # Don't query an empty collection — ChromaDB raises if n_results > count
        count = col.count()
        if count == 0:
            return []
        results = col.query(
            query_texts=[text],
            n_results=min(n_results, count),
            include=["documents", "distances", "metadatas"],
        )
        out: list[dict[str, Any]] = []
        for doc_id, doc, dist, meta in zip(
            results["ids"][0],
            results["documents"][0],
            results["distances"][0],
            results["metadatas"][0],
        ):
            out.append({"id": doc_id, "document": doc, "distance": dist, "metadata": meta or {}})
        return out
    except Exception as exc:  # noqa: BLE001
        log.debug("Chroma query failed (%s): %s", collection_name, exc)
        _mark_embedding_unavailable()
        return None


def _existing_metadata(collection_name: str, ids: list[str]) -> dict[str, dict[str, Any]]:
    if not ids:
        return {}
    try:
        data = _collection(collection_name).get(ids=ids, include=["metadatas"])
        return {str(key): value or {} for key, value in zip(data.get("ids") or [], data.get("metadatas") or [])}
    except Exception:
        return {}


def sync_structured_data(memory_rows: list[dict[str, Any]], episode_rows: list[dict[str, Any]]) -> dict[str, int]:
    """Incrementally index SQLite canonical data. Unchanged metadata emits no embedding request."""
    from . import db
    specs = [
        ("petit_memory", memory_rows, "mem_", "id", lambda r: r["content"], lambda r: {"type": r.get("type", "note"), "source": r.get("source", "explicit"), "created_at": r.get("created_at", "")}, db.update_memory_indexed),
        ("petit_episodes", episode_rows, "episode_", "episode_id", lambda r: "\n".join([r["title"], r["summary"], r.get("decisions", ""), r.get("facts", ""), r.get("work_in_progress", ""), r.get("next_action", "")]), lambda r: {"type": "episode", "title": r["title"], "started_at": r["started_at"], "ended_at": r["ended_at"]}, db.update_episode_indexed),
    ]
    counts: dict[str, int] = {"memory": 0, "episodes": 0}
    for label, rows, prefix, key, text_of, meta_of, mark in specs:
        ids = [f"{prefix}{row[key]}" for row in rows]
        existing = _existing_metadata(label, ids)
        docs: list[tuple[str, str, dict[str, Any]]] = []
        changed: list[int] = []
        for row, doc_id in zip(rows, ids):
            text = text_of(row)
            import hashlib
            digest = row.get("content_hash") or hashlib.sha256(text.encode("utf-8")).hexdigest()
            current = existing.get(doc_id, {})
            if current.get("content_hash") == digest and current.get("embedding_model") == config.EMBED_MODEL and current.get("embedding_version") == config.EMBEDDING_VERSION:
                continue
            docs.append((doc_id, text, {**meta_of(row), "content_hash": digest, "embedding_model": config.EMBED_MODEL, "embedding_version": config.EMBEDDING_VERSION, "indexed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}))
            changed.append(int(row[key]))
        if not docs:
            continue
        indexed = add_many(label, docs)
        if indexed == len(docs):
            for row_id in changed:
                mark(row_id, config.EMBED_MODEL, config.EMBEDDING_VERSION)
        counts["memory" if label == "petit_memory" else "episodes"] = indexed
    return counts


def sync_from_sqlite(memory_rows: list[dict[str, Any]], conv_rows: list[dict[str, Any]]) -> dict[str, int]:
    """Compatibility wrapper; raw conversations are no longer a primary index."""
    return sync_structured_data(memory_rows, [])


def embedding_stats() -> dict[str, int | None]:
    return {
        "requests": _embedding_stats.requests,
        "inputs": _embedding_stats.inputs,
        "last_elapsed_ms": _embedding_stats.last_elapsed_ms,
    }


def reset_embedding_stats() -> None:
    _embedding_stats.requests = 0
    _embedding_stats.inputs = 0
    _embedding_stats.last_elapsed_ms = None
    _embedding_cache.clear()
