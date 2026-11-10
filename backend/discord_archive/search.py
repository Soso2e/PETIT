"""Search engine for Discord archive with FTS5, trigrams, and provenance."""
from __future__ import annotations

import logging
import re
from typing import Any

from .archive import DiscordArchive, FIELDS, utc_iso
from .policy import ArchivePolicy

log = logging.getLogger("petit.discord_archive")
MAX_RESULTS = 50


def bounded_limit(value: Any, default: int = 10) -> int:
    try:
        return max(1, min(MAX_RESULTS, int(value if value is not None else default)))
    except (ValueError, TypeError):
        return default


class ArchiveSearch:
    """Read boundary and query engine for archived Discord messages."""

    def __init__(self, archive: DiscordArchive, policy: ArchivePolicy) -> None:
        self.archive = archive
        self.policy = policy
        self.archive.bind_zone(policy.zone)

    def scope(self, filters: dict[str, Any]) -> tuple[str, list[Any]]:
        clause, args = self.policy.sql_scope()
        parts = [clause, "m.is_deleted=0"]

        for name in ("guild_id", "channel_id", "thread_id", "author_id"):
            val = filters.get(name)
            if val is not None:
                parts.append(f"m.{name}=?")
                args.append(str(val))

        # Channel-level authorization: caller may only see channels they have permission for
        permitted = filters.get("permitted_channels")
        if permitted is not None:
            permitted_set = {str(c) for c in permitted}
            if not permitted_set:
                parts.append("0")  # No channels permitted -> return nothing
            else:
                placeholders = ",".join("?" for _ in permitted_set)
                parts.append(f"(m.channel_id IN ({placeholders}) OR COALESCE(m.thread_id, '') IN ({placeholders}))")
                args.extend(list(permitted_set))
                args.extend(list(permitted_set))

        for name, op in (("since", ">="), ("until", "<=")):
            val = filters.get(name)
            if val:
                parts.append(f"m.created_at{op}?")
                args.append(utc_iso(val))

        return " AND ".join(parts), args

    def search(self, query: str, limit: int = 10, **filters) -> list[dict[str, Any]]:
        query_str = str(query or "").strip()
        if not query_str:
            return []
        if len(query_str) > 2000:
            query_str = query_str[:2000]

        limit = bounded_limit(limit)
        scope, args = self.scope(filters)

        tokens = re.findall(r"\w+", query_str, re.UNICODE)[:32]
        if not tokens:
            return []

        fts_clauses = ['"' + t.replace('"', '""') + '"*' for t in tokens]
        fts_query = " OR ".join(fts_clauses)
        ranks: dict[str, dict[str, int]] = {}
        rows: dict[str, dict[str, Any]] = {}

        with self.archive.connect() as db:
            # 1. FTS5 matching on content + attachments
            fts_sql = (
                f"SELECT m.*, bm25(archive_fts) AS rank FROM archive_fts "
                f"JOIN discord_messages m ON m.rowid=archive_fts.rowid "
                f"WHERE archive_fts MATCH ? AND {scope} ORDER BY rank, m.message_id LIMIT ?"
            )
            hits = list(db.execute(fts_sql, [fts_query] + args + [limit * 4]))

            # 2. Trigram matching for exact substrings (useful for Japanese)
            if len(query_str) >= 3:
                trigram_sql = (
                    f"SELECT m.*, bm25(archive_trigrams) AS rank FROM archive_trigrams "
                    f"JOIN discord_messages m ON m.rowid=archive_trigrams.rowid "
                    f"WHERE archive_trigrams MATCH ? AND {scope} ORDER BY rank, m.message_id LIMIT ?"
                )
                escaped = '"' + query_str.replace('"', '""') + '"'
                hits += list(db.execute(trigram_sql, [escaped] + args + [limit * 4]))

            seen = set()
            for row in sorted(hits, key=lambda r: (r["rank"], r["message_id"])):
                mid = row["message_id"]
                if mid in seen:
                    continue
                seen.add(mid)
                rows[mid] = dict(row)
                ranks[mid] = {"fts": len(seen)}

        # Score with Reciprocal Rank Fusion & exact phrase bonus
        scored_results: list[dict[str, Any]] = []
        for mid, matches in ranks.items():
            score = sum(1.0 / (60.0 + r) for r in matches.values())
            content = rows[mid].get("content") or ""
            exact = query_str.casefold() in content.casefold()
            if exact:
                score += 1.0 / 61.0

            scored_results.append(
                {
                    "message_id": mid,
                    "score": round(score, 6),
                    "match_type": list(matches.keys()) + (["exact"] if exact else []),
                    "data": rows[mid],
                }
            )

        scored_results.sort(key=lambda item: (-item["score"], item["message_id"]))

        permitted = filters.get("permitted_channels")
        permitted_set = {str(c) for c in permitted} if permitted is not None else None

        # Authoritative re-fetch ensuring fresh attachments and deleted status
        final: list[dict[str, Any]] = []
        for item in scored_results[:limit]:
            msg = self.archive.get_message(item["message_id"])
            if msg and not msg["is_deleted"] and self.policy.allows_message(msg):
                if permitted_set is not None:
                    cid = str(msg.get("channel_id") or "")
                    tid = str(msg.get("thread_id") or "")
                    if cid not in permitted_set and tid not in permitted_set:
                        continue
                msg["search_score"] = item["score"]
                msg["match_type"] = item["match_type"]
                final.append(msg)

        return final
