"""Memory tools: save and search notes the user wants PETIT to remember.

search_memory uses ChromaDB semantic search (RAG) when LM Studio embeddings
are available, and falls back to SQLite / Markdown keyword search transparently.
save_memory writes to SQLite (source of truth) and also indexes into Chroma.
"""
from __future__ import annotations

from typing import Any
from datetime import datetime, timezone
import unicodedata

from .. import chroma_client, conversation_search, db, request_context, vault_indexer
from .registry import tool


@tool(
    name="save_memory",
    description=(
        "ユーザーが覚えておいてほしい情報（好み・事実・進行中の作業など）を長期記憶に保存する。"
        "既存知識の訂正・更新は、先にsearch_memoryで正本IDを取得してreplaces_idを指定する。"
        "訂正を追記だけで済ませて矛盾した旧記憶を有効なまま残さない。対象が複数なら確認する。"
        "「これ覚えておいて」のような発話で使う。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "保存する内容"},
            "replaces_id": {"type": "integer", "description": "明示的に訂正・更新する既存記憶ID。旧行は削除せず置き換え先を記録する。"},
            "valid_until": {"type": "string", "description": "明示された有効期限のISO日時。期限を推測しない。省略時は無期限。"},
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
def save_memory(content: str, type: str = "note", replaces_id: int | None = None,
                valid_until: str | None = None) -> dict[str, Any]:
    if valid_until:
        parsed = datetime.fromisoformat(valid_until)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        valid_until = parsed.astimezone(timezone.utc).isoformat()
    visibility = "local_only" if conversation_search.local_only_context() else "standard"
    _, session_id = request_context.current_ids()
    memory_id, created = db.save_memory_item(content, type, "explicit", visibility=visibility,
        source_session_id=session_id, replaces_id=replaces_id, valid_until=valid_until)
    if visibility == "standard" and created:
        chroma_client.add("petit_memory", f"mem_{memory_id}", content,
                          {"created_at": db.now_iso(), "type": type, "source": "explicit"})
    if replaces_id is not None and replaces_id != memory_id:
        chroma_client.delete_ids("petit_memory", [f"mem_{replaces_id}"])
    with db.get_connection() as connection:
        saved = dict(connection.execute("SELECT * FROM memory WHERE id=?", (memory_id,)).fetchone())
    return {**saved, "saved": True, "created": created, "replaces_id": replaces_id}


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
            "limit": {"type": "integer", "description": "追加検索で読む最大件数。通常文脈は最大5項目", "default": 5},
            "offset": {"type": "integer", "description": "必要な時の追加検索位置", "default": 0},
            "include_inactive": {"type": "boolean", "description": "訂正履歴を調べる時だけ、置換済み・期限切れを含める", "default": False},
            "include_vault": {
                "type": "boolean",
                "description": "既存Obsidian vaultも検索対象に含めるか",
                "default": True,
            },
        },
        "required": ["query"],
    },
)
def search_memory(query: str, limit: int = 5, include_vault: bool = True, offset: int = 0,
                  include_inactive: bool = False) -> dict[str, Any]:
    limit, offset = max(1, min(int(limit), 50)), max(0, min(int(offset), 100000))
    private = conversation_search.local_only_context()
    # --- Semantic search (RAG) ---
    mem_results = None if private else chroma_client.query("petit_memory", query, n_results=min(50, limit + offset))
    episode_results = None if private else chroma_client.query("petit_episodes", query, n_results=limit)
    vault_results = (
        chroma_client.query(vault_indexer.COLLECTION_NAME, query, n_results=limit)
        if include_vault and not private
        else []
    )

    # Use semantic results only if at least one collection actually returned matches.
    # None = embedding failed (LM Studio down); [] = no matches or empty collection.
    has_semantic = bool(mem_results) or bool(episode_results) or bool(vault_results)

    if has_semantic:
        ids = [int(r["id"].removeprefix("mem_")) for r in (mem_results or [])
               if str(r.get("id", "")).startswith("mem_") and str(r["id"])[4:].isdigit()]
        with db.get_connection() as connection:
            canonical = {f"mem_{r['id']}": dict(r) for r in connection.execute(
                "SELECT * FROM memory WHERE id IN (" + ",".join("?" for _ in ids) + ") AND visibility='standard'" + (
                    "" if include_inactive else " AND superseded_by IS NULL AND (valid_until IS NULL OR valid_until>?)"),
                ids + ([] if include_inactive else [db.now_iso()]))}
        memories = [{**canonical[r["id"]], "relevance": round(1-r["distance"], 3)}
                    for r in (mem_results or []) if r["id"] in canonical][offset:offset + limit]
        episodes = [
            {
                "text": r["document"],
                "historical_summary": True, "type": "episode", "title": r["metadata"].get("title", ""), "started_at": r["metadata"].get("started_at", ""),
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
        if memories or episodes or vault_notes:
            return {
                "query": query,
                "search_type": "semantic",
                "memories": memories,
                "episodes": episodes,
                "vault_notes": vault_notes,
                "found": len(memories) + len(episodes) + len(vault_notes),
            }

    # --- Fallback: SQLite LIKE search + Markdown keyword search ---
    like = conversation_search.literal_like(query)
    words = query.split()[:8] or [query]
    word_where = " AND ".join("content LIKE ? ESCAPE '\\'" for _ in words)
    scope = ("" if private else " AND visibility='standard'") + (
        "" if include_inactive else " AND superseded_by IS NULL AND (valid_until IS NULL OR valid_until>?)")
    scope_values = [] if include_inactive else [db.now_iso()]
    word_values = [conversation_search.literal_like(word) for word in words]
    related = False
    with db.get_connection() as conn:
        mem_rows = conn.execute(
            "SELECT * FROM memory WHERE " + word_where + scope + " ORDER BY id DESC LIMIT ? OFFSET ?",
            [*word_values, *scope_values, limit, offset],
        ).fetchall()
        has_literal = mem_rows or conn.execute("SELECT 1 FROM memory WHERE " + word_where + scope + " LIMIT 1",
                                               [*word_values, *scope_values]).fetchone()
        if not has_literal:
            # Generic character retrieval, not an intent/phrase router. Japanese
            # prose may contain particles between a name and the fact's subject.
            compact_query = "".join(unicodedata.normalize("NFKC", query).casefold().split())
            grams = list(dict.fromkeys(compact_query[i:i+2] for i in range(len(compact_query)-1)))[:24]
            if grams:
                score = " + ".join("CASE WHEN content LIKE ? ESCAPE '\\' THEN 1 ELSE 0 END" for _ in grams)
                mem_rows = conn.execute(
                    "SELECT * FROM (SELECT memory.*,(" + score + ") AS term_matches FROM memory WHERE 1=1" +
                    scope + ") WHERE term_matches>0 ORDER BY term_matches DESC,id DESC LIMIT ? OFFSET ?",
                    [*[conversation_search.literal_like(g) for g in grams], *scope_values, limit, offset]).fetchall()
                related = True
        episode_rows = conn.execute(
            "SELECT episode_id, started_at, title, summary FROM conversation_episodes WHERE title LIKE ? OR summary LIKE ? OR facts LIKE ? ORDER BY episode_id DESC LIMIT ?",
            (like, like, like, limit),
        ).fetchall()

    memories = [{**dict(r), "match_kind": "related_candidate" if related else "literal_keywords"} for r in mem_rows]
    episodes = [{"historical_summary": True, "type": "episode", "title": r["title"], "summary": r["summary"], "started_at": r["started_at"]} for r in episode_rows]
    vault_notes = vault_indexer.keyword_search(query, limit=limit) if include_vault else []
    return {
        "query": query,
        "search_type": "related_candidates" if related else "keyword",
        "note": "意味検索で利用できる正本がないためSQLite/Markdownを検索しました。",
        "memories": memories,
        "episodes": episodes,
        "vault_notes": vault_notes,
        "found": len(memories) + len(episodes) + len(vault_notes),
        "candidate_warning": "部分一致候補は内容を確認し、同じ事実か判断する。検索不一致だけで保存されていないと断定しない。" if related else None,
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
