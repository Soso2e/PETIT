"""Context recovery tools: handoff notes and restore context."""
from __future__ import annotations

from typing import Any

from .. import chroma_client, db, markdown_export
from .registry import tool


@tool(
    name="create_handoff_note",
    description=(
        "作業を中断・終了するときの引き継ぎメモを保存する。"
        "今やっていたこと、止まった場所、次の一手、詰まりを残す。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "current_project": {"type": "string", "description": "作業名・プロジェクト名。任意。"},
            "stopped_at": {"type": "string", "description": "どこで止まったか。任意。"},
            "next_action": {"type": "string", "description": "再開時に最初にやる具体的な一手。"},
            "blockers": {"type": "string", "description": "詰まり・未確認・注意点。任意。"},
            "note": {"type": "string", "description": "補足メモ。任意。"},
        },
        "required": ["next_action"],
    },
)
def create_handoff_note(
    next_action: str,
    current_project: str | None = None,
    stopped_at: str | None = None,
    blockers: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    handoff_id = db.save_handoff_note(
        current_project=current_project,
        stopped_at=stopped_at,
        next_action=next_action,
        blockers=blockers,
        note=note,
    )
    text = _format_handoff(
        {
            "id": handoff_id,
            "current_project": current_project,
            "stopped_at": stopped_at,
            "next_action": next_action,
            "blockers": blockers,
            "note": note,
        }
    )
    _save_memory(text, mem_type="project")
    markdown_export.append_memory(text, "handoff")
    return {
        "saved": True,
        "id": handoff_id,
        "current_project": current_project,
        "next_action": next_action,
        "blockers": blockers,
    }


@tool(
    name="restore_context",
    description=(
        "中断後に作業文脈を復元する。直近の引き継ぎ、要約、関連記憶から"
        "再開に必要な情報を返す。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "復帰したい作業・話題。省略可。"},
            "limit": {"type": "integer", "description": "取得件数。既定は5。", "default": 5},
        },
    },
)
def restore_context(query: str | None = None, limit: int = 5) -> dict[str, Any]:
    handoffs = db.recent_handoff_notes(limit=limit)
    summaries = db.recent_summaries(limit=2)
    memories = _search_relevant_memory(query or "", limit=limit)

    latest = handoffs[-1] if handoffs else None
    return {
        "restored": bool(handoffs or summaries or memories),
        "query": query,
        "latest_handoff": latest,
        "recent_handoffs": handoffs,
        "recent_summaries": summaries,
        "relevant_memories": memories,
        "suggested_first_step": latest.get("next_action") if latest else None,
    }


def _save_memory(content: str, mem_type: str) -> None:
    now = db.now_iso()
    with db.get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO memory (created_at, type, content) VALUES (?, ?, ?)",
            (now, mem_type, content),
        )
        memory_id = int(cur.lastrowid)
    chroma_client.add(
        "petit_memory",
        doc_id=f"mem_{memory_id}",
        text=content,
        metadata={"type": mem_type, "created_at": now, "source": "handoff"},
    )


def _search_relevant_memory(query: str, limit: int) -> list[dict[str, Any]]:
    if query:
        results = chroma_client.query("petit_memory", query, n_results=limit)
        if results:
            return [
                {
                    "content": r["document"],
                    "type": r["metadata"].get("type", "note"),
                    "created_at": r["metadata"].get("created_at", ""),
                }
                for r in results
            ]
    rows = db.all_memory()[-limit:]
    return [{"content": r["content"], "type": r["type"], "created_at": r["created_at"]} for r in rows]


def _format_handoff(item: dict[str, Any]) -> str:
    parts = ["引き継ぎメモ"]
    if item.get("current_project"):
        parts.append(f"作業: {item['current_project']}")
    if item.get("stopped_at"):
        parts.append(f"止まった場所: {item['stopped_at']}")
    parts.append(f"次の一手: {item['next_action']}")
    if item.get("blockers"):
        parts.append(f"詰まり: {item['blockers']}")
    if item.get("note"):
        parts.append(f"メモ: {item['note']}")
    return " / ".join(parts)
