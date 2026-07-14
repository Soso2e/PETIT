"""Memory tools: save and search notes the user wants PETIT to remember.

search_memory uses ChromaDB semantic search (RAG) when LM Studio embeddings
are available, and falls back to SQLite / Markdown keyword search transparently.
save_memory writes to SQLite (source of truth) and also indexes into Chroma.
"""
from __future__ import annotations

from typing import Any

from .. import chroma_client, db, vault_indexer
from .registry import tool


@tool(
    name="save_memory",
    description=(
        "ユーザーが覚えておいてほしい情報（好み・事実・進行中の作業など）を長期記憶に保存する。"
        "「これ覚えておいて」のような発話で使う。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "保存する内容"},
            "type": {
                "type": "string",
                "description": "記憶の種類（例: note, preference, fact, project）",
                "default": "note",
            },
        },
        "required": ["content"],
    },
    requires_confirmation=True,
)
def save_memory(content: str, type: str = "note") -> dict[str, Any]:
    memory_id, created = db.save_memory_item(content, type, "explicit")
    chroma_client.sync_structured_data(db.all_memory(), db.all_episodes())
    return {"saved": True, "created": created, "id": memory_id, "type": type, "content": content, "source": "explicit"}


@tool(
    name="search_memory",
    description=(
        "過去に保存した記憶・会話ログ・要約・Obsidian vaultを意味的に検索する（RAG）。"
        "「昨日何してたっけ？」「前に話した○○」「○○について覚えてる？」のような発話で使う。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "検索したい内容・質問"},
            "limit": {"type": "integer", "description": "最大件数", "default": 8},
            "include_vault": {
                "type": "boolean",
                "description": "既存Obsidian vaultも検索対象に含めるか",
                "default": True,
            },
        },
        "required": ["query"],
    },
)
def search_memory(query: str, limit: int = 8, include_vault: bool = True) -> dict[str, Any]:
    # --- Semantic search (RAG) ---
    mem_results = chroma_client.query("petit_memory", query, n_results=limit)
    episode_results = chroma_client.query("petit_episodes", query, n_results=limit)
    vault_results = (
        chroma_client.query(vault_indexer.COLLECTION_NAME, query, n_results=limit)
        if include_vault
        else []
    )

    # Use semantic results only if at least one collection actually returned matches.
    # None = embedding failed (LM Studio down); [] = no matches or empty collection.
    has_semantic = bool(mem_results) or bool(episode_results) or bool(vault_results)

    if has_semantic:
        memories = [
            {
                "content": r["document"],
                "created_at": r["metadata"].get("created_at", ""),
                "type": r["metadata"].get("type", "note"),
                "relevance": round(1 - r["distance"], 3),  # cosine: 0=identical
            }
            for r in (mem_results or [])
        ]
        episodes = [
            {
                "text": r["document"],
                "type": "episode", "title": r["metadata"].get("title", ""), "started_at": r["metadata"].get("started_at", ""),
                "relevance": round(1 - r["distance"], 3),
            }
            for r in (episode_results or [])
        ]
        vault_notes = [
            {
                "text": r["document"],
                "source_path": r["metadata"].get("source_path", ""),
                "relative_path": r["metadata"].get("relative_path", ""),
                "heading": r["metadata"].get("heading", ""),
                "modified_at": r["metadata"].get("modified_at", ""),
                "relevance": round(1 - r["distance"], 3),
            }
            for r in (vault_results or [])
        ]
        return {
            "query": query,
            "search_type": "semantic",
            "memories": memories,
            "episodes": episodes,
            "vault_notes": vault_notes,
            "found": len(memories) + len(episodes) + len(vault_notes),
        }

    # --- Fallback: SQLite LIKE search + Markdown keyword search ---
    like = f"%{query}%"
    with db.get_connection() as conn:
        mem_rows = conn.execute(
            "SELECT id, created_at, type, content FROM memory "
            "WHERE content LIKE ? ORDER BY id DESC LIMIT ?",
            (like, limit),
        ).fetchall()
        episode_rows = conn.execute(
            "SELECT episode_id, started_at, title, summary FROM conversation_episodes WHERE title LIKE ? OR summary LIKE ? OR facts LIKE ? ORDER BY episode_id DESC LIMIT ?",
            (like, like, like, limit),
        ).fetchall()

    memories = [
        {"content": r["content"], "created_at": r["created_at"], "type": r["type"]}
        for r in mem_rows
    ]
    episodes = [{"type": "episode", "title": r["title"], "summary": r["summary"], "started_at": r["started_at"]} for r in episode_rows]
    vault_notes = vault_indexer.keyword_search(query, limit=limit) if include_vault else []
    return {
        "query": query,
        "search_type": "keyword",
        "note": "embedding モデルが利用不可のためキーワード検索にフォールバックしました。",
        "memories": memories,
        "episodes": episodes,
        "vault_notes": vault_notes,
        "found": len(memories) + len(episodes) + len(vault_notes),
    }


@tool(
    name="summarize_now",
    description=(
        "これまでの未整理の会話を今すぐまとめて長期記憶に蓄積する。"
        "「ここまでの話まとめておいて」「今の状況を記録して」のような発話で使う。"
    ),
    parameters={"type": "object", "properties": {}},
    requires_confirmation=True,
)
def summarize_now() -> dict[str, Any]:
    # Imported lazily to avoid a circular import (summarizer -> tools 経由)
    from .. import summarizer

    return summarizer.summarize_pending(kind="interval", force=True)


@tool(
    name="sync_obsidian_vault",
    description=(
        "設定済みの既存Obsidian vaultを読み直し、MarkdownノートをRAG検索用にChromaへ索引化する。"
        "vaultにノートを追加・編集した後、すぐPETITに反映したいときに使う。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "max_files": {
                "type": "integer",
                "description": "今回同期する最大Markdownファイル数。未指定なら設定値を使う。",
            }
        },
    },
)
def sync_obsidian_vault(max_files: int | None = None) -> dict[str, Any]:
    return vault_indexer.index_configured_vaults(max_files=max_files)
