"""Memory tools: save and search notes the user wants PETIT to remember.

MVP uses simple SQLite storage with LIKE search. Semantic search (Chroma)
can replace search_memory later without changing the tool interface.
"""
from __future__ import annotations

from typing import Any

from .. import db
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
)
def save_memory(content: str, type: str = "note") -> dict[str, Any]:
    with db.get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO memory (created_at, type, content) VALUES (?, ?, ?)",
            (db.now_iso(), type, content),
        )
        memory_id = int(cur.lastrowid)
    return {"saved": True, "id": memory_id, "type": type, "content": content}


@tool(
    name="search_memory",
    description=(
        "過去に保存した記憶や会話ログを検索する。"
        "「昨日何してたっけ？」「前に話した○○」のような発話で使う。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "検索キーワード"},
            "limit": {"type": "integer", "description": "最大件数", "default": 10},
        },
        "required": ["query"],
    },
)
def search_memory(query: str, limit: int = 10) -> dict[str, Any]:
    like = f"%{query}%"
    with db.get_connection() as conn:
        mem_rows = conn.execute(
            "SELECT id, created_at, type, content FROM memory "
            "WHERE content LIKE ? ORDER BY id DESC LIMIT ?",
            (like, limit),
        ).fetchall()
        conv_rows = conn.execute(
            "SELECT id, timestamp, user_text, assistant_text FROM conversations "
            "WHERE user_text LIKE ? OR assistant_text LIKE ? ORDER BY id DESC LIMIT ?",
            (like, like, limit),
        ).fetchall()

    return {
        "query": query,
        "memories": [dict(r) for r in mem_rows],
        "conversations": [dict(r) for r in conv_rows],
        "found": len(mem_rows) + len(conv_rows),
    }
