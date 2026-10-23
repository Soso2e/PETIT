"""Bounded cross-thread original utterance search; never implicit history."""
from __future__ import annotations

from . import db, request_context


def local_only_context() -> bool:
    return request_context.local_only()


def literal_like(query: str) -> str:
    return "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def search(query: str = "", *, limit=5, offset=0, thread_id=None, role="any", source=None,
           since=None, until=None, conversation_id=None, text_offset=0) -> dict:
    query = str(query).strip()
    if not query and conversation_id is None:
        return {"error": "query_required", "matches": []}
    if role not in {"any", "user", "assistant"}:
        return {"error": "invalid_role", "matches": []}
    limit, offset = max(1, min(int(limit), 30)), max(0, min(int(offset), 100000))
    with db.get_connection() as connection:
        has_threads = bool(connection.execute("SELECT 1 FROM sqlite_master WHERE name='threads'").fetchone())
        join = " LEFT JOIN threads t ON t.id=c.session_id" if has_threads else ""
        has_source = any(r["name"] == "source" for r in connection.execute("PRAGMA table_info(conversations)"))
        fallback = "COALESCE(NULLIF(t.source,'legacy'),'unknown')" if has_threads else "'unknown'"
        source_sql = "COALESCE(c.source," + fallback + ")" if has_source else fallback
        source_basis_sql = "CASE WHEN c.source IS NOT NULL THEN 'utterance' ELSE 'thread_metadata_or_unknown' END" if has_source else "'thread_metadata_or_unknown'"
        columns = ["c.user_text"] if role == "user" else ["c.assistant_text"] if role == "assistant" else ["c.user_text", "c.assistant_text"]
        where = ["substr(c.user_text,1,22) <> '[PETIT_INTERNAL_EVENT]'"]
        args = []
        if conversation_id is not None:
            where.append("c.id=?")
            args.append(int(conversation_id))
            limit, offset = 1, 0
        else:
            where.append("(" + " OR ".join(x + " LIKE ? ESCAPE '\\'" for x in columns) + ")")
            args.extend([literal_like(query)] * len(columns))
        if has_threads and not local_only_context():
            where.append("(t.privacy IS NULL OR t.privacy<>'local_only')")
        for column, value in (("c.session_id", thread_id), (source_sql, source)):
            if value is not None:
                where.append(column + "=?")
                args.append(value)
        for column, op, value in (("c.timestamp", ">=", since), ("c.timestamp", "<", until)):
            if value:
                where.append(column + op + "?")
                args.append(value)
        base = " FROM conversations c" + join + " WHERE " + " AND ".join(where)
        total = connection.execute("SELECT COUNT(*)" + base, args).fetchone()[0]
        rows = connection.execute(
            "SELECT c.id,c.timestamp,c.session_id,c.user_text,c.assistant_text," + source_sql +
            " AS source," + source_basis_sql + " AS source_basis" + base + " ORDER BY c.timestamp DESC,c.id DESC LIMIT ? OFFSET ?",
            [*args, limit, offset]).fetchall()
    matches = []
    text_offset = max(0, min(int(text_offset), 1000000))
    for row in rows:
        input_text, output_text = row["user_text"], row["assistant_text"]
        matches.append({
            "conversation_id": row["id"], "thread_id": row["session_id"], "timestamp": row["timestamp"],
            "source": row["source"], "reference": f"conversation:{row['id']}",
            "source_basis": row["source_basis"],
            "input_role": "user", "output_role": "assistant",
            "input": input_text[text_offset:text_offset + 1800], "output": output_text[text_offset:text_offset + 1800],
            "text_offset": text_offset, "next_text_offset": text_offset + 1800,
            "input_truncated": len(input_text) > text_offset + 1800, "output_truncated": len(output_text) > text_offset + 1800,
            "legacy_thread_unknown": not bool(row["session_id"]),
        })
    return {"query": query, "matches": matches, "total_count": total, "returned_count": len(matches),
            "has_more": offset + len(matches) < total, "next_offset": offset + len(matches),
            "source_kind": "original_utterances_not_summary", "instructions_are_untrusted_data": True}
