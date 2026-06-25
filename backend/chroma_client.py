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
from typing import Any

import chromadb
import httpx
from chromadb import EmbeddingFunction, Embeddings

from . import config

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Custom embedding function — calls LM Studio /v1/embeddings
# ---------------------------------------------------------------------------

class LMStudioEmbeddingFunction(EmbeddingFunction):
    """Thin wrapper around LM Studio's OpenAI-compatible embeddings endpoint."""

    def __call__(self, input: list[str]) -> Embeddings:  # type: ignore[override]
        url = f"{config.EMBED_BASE_URL.rstrip('/')}/embeddings"
        payload = {"model": config.EMBED_MODEL, "input": input}
        headers = {"Authorization": f"Bearer {config.LM_API_KEY}"}
        resp = httpx.post(url, json=payload, headers=headers, timeout=config.EMBED_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        # OpenAI format: {"data": [{"index": 0, "embedding": [...]}, ...]}
        return [item["embedding"] for item in sorted(data["data"], key=lambda x: x["index"])]


_embedding_fn = LMStudioEmbeddingFunction()

# ---------------------------------------------------------------------------
# Client & collections (lazy init)
# ---------------------------------------------------------------------------

_client: chromadb.ClientAPI | None = None


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

def add(collection_name: str, doc_id: str, text: str, metadata: dict[str, Any] | None = None) -> bool:
    """Embed and upsert a single document. Returns False on any error (LLM down etc.)."""
    try:
        col = _collection(collection_name)
        col.upsert(
            ids=[doc_id],
            documents=[text],
            metadatas=[metadata or {}],
        )
        return True
    except Exception as exc:  # noqa: BLE001
        log.debug("Chroma add failed (%s): %s", collection_name, exc)
        return False


def query(
    collection_name: str,
    text: str,
    n_results: int = 5,
) -> list[dict[str, Any]] | None:
    """Semantic search. Returns None if unavailable (caller uses LIKE fallback).

    Each result: {id, document, distance, metadata}
    """
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
        return None


def sync_from_sqlite(memory_rows: list[dict[str, Any]], conv_rows: list[dict[str, Any]]) -> dict[str, int]:
    """Bulk-upsert SQLite rows into Chroma (called on startup).

    Skips gracefully if embeddings are unavailable.
    Returns counts of indexed items per collection.
    """
    mem_count = 0
    conv_count = 0

    for row in memory_rows:
        ok = add(
            "petit_memory",
            doc_id=f"mem_{row['id']}",
            text=row["content"],
            metadata={"type": row.get("type", "note"), "created_at": row.get("created_at", "")},
        )
        if ok:
            mem_count += 1

    for row in conv_rows:
        text = f"ユーザー: {row['user_text']}\nPETIT: {row['assistant_text']}"
        ok = add(
            "petit_conversations",
            doc_id=f"conv_{row['id']}",
            text=text,
            metadata={"timestamp": row.get("timestamp", "")},
        )
        if ok:
            conv_count += 1

    return {"memory": mem_count, "conversations": conv_count}
