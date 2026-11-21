"""Self-knowledge SQLite FTS5/trigram index for PETIT's own documentation.

Indexes ``Concept.md``, ``PROGRESS.md``, and non-archive Markdown files under
``docs/`` into ``storage/petit_docs.db`` so any Brain can search PETIT's own
usage, features, architecture, and status before answering questions about PETIT.
"""
from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config

log = logging.getLogger(__name__)

_SYNC_LOCK = threading.Lock()
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_STATUS_RE = re.compile(r"Status\s*:\s*(.+)", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[a-zA-Z0-9_+-]{2,}|[一-龯ぁ-んァ-ヶー]{2,}")
_DEFAULT_MAX_CHARS = 1400
_DEFAULT_OVERLAP = 160
_EXCERPT_CHARS = 900


def default_db_path() -> Path:
    return config.STORAGE_DIR / "petit_docs.db"


def petit_version(base_dir: Path | None = None) -> str:
    root = base_dir or config.BASE_DIR
    version_file = root / "VERSION"
    if not version_file.is_file():
        return ""
    return version_file.read_text(encoding="utf-8-sig").strip()


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS doc_files (
            doc_path TEXT PRIMARY KEY,
            file_hash TEXT NOT NULL,
            mtime_ns INTEGER NOT NULL,
            size INTEGER NOT NULL,
            category TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS doc_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_path TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            heading TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL,
            UNIQUE(doc_path, chunk_index)
        );

        CREATE INDEX IF NOT EXISTS idx_doc_chunks_path ON doc_chunks(doc_path);
        CREATE INDEX IF NOT EXISTS idx_doc_chunks_category ON doc_chunks(category);

        CREATE VIRTUAL TABLE IF NOT EXISTS doc_chunks_fts USING fts5(
            title,
            heading,
            content,
            prefix='2,3'
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS doc_chunks_trigrams USING fts5(
            title,
            heading,
            content,
            tokenize='trigram'
        );

        CREATE TRIGGER IF NOT EXISTS trg_doc_chunks_insert AFTER INSERT ON doc_chunks BEGIN
            INSERT INTO doc_chunks_fts(rowid, title, heading, content)
                VALUES (NEW.id, NEW.title, NEW.heading, NEW.content);
            INSERT INTO doc_chunks_trigrams(rowid, title, heading, content)
                VALUES (NEW.id, NEW.title, NEW.heading, NEW.content);
        END;

        CREATE TRIGGER IF NOT EXISTS trg_doc_chunks_update AFTER UPDATE ON doc_chunks BEGIN
            DELETE FROM doc_chunks_fts WHERE rowid=OLD.id;
            DELETE FROM doc_chunks_trigrams WHERE rowid=OLD.id;
            INSERT INTO doc_chunks_fts(rowid, title, heading, content)
                VALUES (NEW.id, NEW.title, NEW.heading, NEW.content);
            INSERT INTO doc_chunks_trigrams(rowid, title, heading, content)
                VALUES (NEW.id, NEW.title, NEW.heading, NEW.content);
        END;

        CREATE TRIGGER IF NOT EXISTS trg_doc_chunks_delete AFTER DELETE ON doc_chunks BEGIN
            DELETE FROM doc_chunks_fts WHERE rowid=OLD.id;
            DELETE FROM doc_chunks_trigrams WHERE rowid=OLD.id;
        END;
        """
    )


def _iter_doc_files(base_dir: Path) -> list[tuple[str, str, Path]]:
    items: list[tuple[str, str, Path]] = []
    for name, category in (("Concept.md", "concept"), ("PROGRESS.md", "progress")):
        path = base_dir / name
        if path.is_file():
            items.append((name, category, path))

    docs_dir = base_dir / "docs"
    if docs_dir.is_dir():
        for path in sorted(docs_dir.rglob("*.md")):
            rel = path.relative_to(base_dir)
            parts = rel.parts
            if len(parts) >= 2 and parts[1].casefold() == "archive":
                continue
            category = parts[1] if len(parts) >= 3 else "docs"
            items.append((rel.as_posix(), category, path))
    return items


def _extract_title_and_status(text: str, doc_path: str) -> tuple[str, str]:
    title = Path(doc_path).stem
    status = ""
    in_fence = False
    lines = text.splitlines()
    for idx, raw in enumerate(lines[:40]):
        stripped = raw.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if title == Path(doc_path).stem:
            m = _HEADING_RE.match(stripped)
            if m and len(m.group(1)) == 1:
                title = m.group(2).strip()
                continue
        if not status and idx < 25:
            sm = _STATUS_RE.search(stripped)
            if sm:
                status = sm.group(1).replace("**", "").strip().strip("`")
    return title, status


def _split_long_text(text: str, max_chars: int, overlap: int) -> list[str]:
    clean = text.strip()
    if not clean:
        return []
    if len(clean) <= max_chars:
        return [clean]

    parts: list[str] = []
    start = 0
    step = max(200, max_chars - overlap)
    while start < len(clean):
        end = min(len(clean), start + max_chars)
        if end < len(clean):
            split_at = clean.rfind("\n\n", start + step // 2, end)
            if split_at == -1:
                split_at = clean.rfind("\n", start + step // 2, end)
            if split_at > start:
                end = split_at
        piece = clean[start:end].strip()
        if piece:
            parts.append(piece)
        if end >= len(clean):
            break
        start = max(start + 1, end - overlap)
    return parts


def _split_markdown_chunks(
    text: str,
    default_title: str,
    *,
    max_chars: int = _DEFAULT_MAX_CHARS,
    overlap: int = _DEFAULT_OVERLAP,
) -> list[tuple[str, str]]:
    """Split Markdown by headings while ignoring headings inside fenced code blocks."""
    sections: list[tuple[str, list[str]]] = []
    stack: list[tuple[int, str]] = []
    current_heading = default_title
    current_lines: list[str] = []
    in_fence = False

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            current_lines.append(line)
            continue

        if not in_fence:
            m = _HEADING_RE.match(stripped)
            if m:
                if any(item.strip() for item in current_lines):
                    sections.append((current_heading, current_lines))
                    current_lines = []
                level = len(m.group(1))
                heading_text = m.group(2).strip()
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, heading_text))
                current_heading = " > ".join(h for _, h in stack)
                continue

        current_lines.append(line)

    if any(item.strip() for item in current_lines):
        sections.append((current_heading, current_lines))

    chunks: list[tuple[str, str]] = []
    for heading, lines in sections:
        body = "\n".join(lines).strip()
        if not body:
            continue
        for piece in _split_long_text(body, max_chars=max_chars, overlap=overlap):
            chunks.append((heading, piece))

    if not chunks and text.strip():
        for piece in _split_long_text(text, max_chars=max_chars, overlap=overlap):
            chunks.append((default_title, piece))
    return chunks


def sync_petit_docs(
    *,
    db_path: Path | None = None,
    base_dir: Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Incrementally sync PETIT documentation Markdown files into SQLite FTS5."""
    root = (base_dir or config.BASE_DIR).resolve()
    target_db = db_path or default_db_path()

    with _SYNC_LOCK:
        files = _iter_doc_files(root)
        now = datetime.now(timezone.utc).isoformat()
        added = 0
        updated = 0
        skipped = 0
        deleted = 0
        total_chunks = 0

        with _connect(target_db) as conn:
            _ensure_schema(conn)
            existing = {
                row["doc_path"]: dict(row)
                for row in conn.execute(
                    "SELECT doc_path, file_hash, mtime_ns, size FROM doc_files"
                ).fetchall()
            }
            seen_paths: set[str] = set()

            for doc_path, category, abs_path in files:
                seen_paths.add(doc_path)
                try:
                    stat = abs_path.stat()
                except OSError:
                    continue

                prev = existing.get(doc_path)
                if (
                    not force
                    and prev is not None
                    and prev["mtime_ns"] == stat.st_mtime_ns
                    and prev["size"] == stat.st_size
                ):
                    skipped += 1
                    continue

                raw_bytes = abs_path.read_bytes()
                file_hash = hashlib.sha256(raw_bytes).hexdigest()
                if not force and prev is not None and prev["file_hash"] == file_hash:
                    conn.execute(
                        "UPDATE doc_files SET mtime_ns=?, size=?, updated_at=? WHERE doc_path=?",
                        (stat.st_mtime_ns, stat.st_size, now, doc_path),
                    )
                    skipped += 1
                    continue

                text = raw_bytes.decode("utf-8-sig", errors="replace")
                title, status = _extract_title_and_status(text, doc_path)
                chunks = _split_markdown_chunks(text, title)

                conn.execute("DELETE FROM doc_chunks WHERE doc_path=?", (doc_path,))
                for idx, (heading, content) in enumerate(chunks):
                    conn.execute(
                        """
                        INSERT INTO doc_chunks(doc_path, chunk_index, category, title, heading, status, content)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (doc_path, idx, category, title, heading, status, content),
                    )
                conn.execute(
                    """
                    INSERT INTO doc_files(doc_path, file_hash, mtime_ns, size, category, title, status, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(doc_path) DO UPDATE SET
                        file_hash=excluded.file_hash,
                        mtime_ns=excluded.mtime_ns,
                        size=excluded.size,
                        category=excluded.category,
                        title=excluded.title,
                        status=excluded.status,
                        updated_at=excluded.updated_at
                    """,
                    (doc_path, file_hash, stat.st_mtime_ns, stat.st_size, category, title, status, now),
                )
                total_chunks += len(chunks)
                if prev is None:
                    added += 1
                else:
                    updated += 1

            stale_paths = [p for p in existing if p not in seen_paths]
            for stale in stale_paths:
                conn.execute("DELETE FROM doc_chunks WHERE doc_path=?", (stale,))
                conn.execute("DELETE FROM doc_files WHERE doc_path=?", (stale,))
                deleted += 1

            chunk_count = conn.execute("SELECT COUNT(*) FROM doc_chunks").fetchone()[0]
            file_count = conn.execute("SELECT COUNT(*) FROM doc_files").fetchone()[0]

        return {
            "db_path": str(target_db),
            "files": file_count,
            "chunks": chunk_count,
            "added": added,
            "updated": updated,
            "skipped": skipped,
            "deleted": deleted,
            "indexed_chunks": total_chunks,
        }


def _extract_tokens(query: str) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for match in _TOKEN_RE.findall(query):
        key = match.casefold()
        if key not in seen:
            seen.add(key)
            tokens.append(match)
    if not tokens:
        stripped = query.strip()
        if stripped:
            tokens.append(stripped)
    return tokens[:16]


def _make_excerpt(content: str, tokens: list[str], max_chars: int = _EXCERPT_CHARS) -> str:
    clean = content.strip()
    if len(clean) <= max_chars:
        return clean

    lowered = clean.casefold()
    hit_pos = -1
    for token in tokens:
        idx = lowered.find(token.casefold())
        if idx != -1 and (hit_pos == -1 or idx < hit_pos):
            hit_pos = idx

    if hit_pos <= 0:
        return clean[:max_chars].rstrip() + "..."
    start = max(0, hit_pos - max_chars // 4)
    end = min(len(clean), start + max_chars)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(clean) else ""
    return prefix + clean[start:end].strip() + suffix


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_petit_docs(
    query: str,
    *,
    category: str | None = None,
    limit: int = 5,
    db_path: Path | None = None,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """Search PETIT's own documentation DB with FTS5, trigrams, and LIKE fallback."""
    query_str = str(query or "").strip()
    bounded_limit = max(1, min(int(limit), 10))
    version = petit_version(base_dir)
    if not query_str:
        return {"query": "", "petit_version": version, "category": category, "count": 0, "results": []}

    root = (base_dir or config.BASE_DIR).resolve()
    target_db = db_path or default_db_path()
    sync_petit_docs(db_path=target_db, base_dir=root)

    tokens = _extract_tokens(query_str)
    cat_filter = str(category).strip().casefold() if category else ""
    cat_clause = " AND LOWER(c.category) = ?" if cat_filter else ""
    cat_args: list[Any] = [cat_filter] if cat_filter else []

    scored: dict[int, tuple[float, sqlite3.Row]] = {}

    def _add_score(row: sqlite3.Row, delta: float) -> None:
        cid = int(row["id"])
        prev_score = scored[cid][0] if cid in scored else 0.0
        scored[cid] = (prev_score + delta, row)

    with _connect(target_db) as conn:
        # 1. FTS5 token search (BM25 weights: title=3, heading=2, content=1)
        fts_clauses = ['"' + t.replace('"', '""') + '"*' for t in tokens]
        if fts_clauses:
            fts_query = " OR ".join(fts_clauses)
            try:
                rows = conn.execute(
                    f"""
                    SELECT c.*, bm25(doc_chunks_fts, 3.0, 2.0, 1.0) AS rank
                    FROM doc_chunks_fts
                    JOIN doc_chunks c ON c.id = doc_chunks_fts.rowid
                    WHERE doc_chunks_fts MATCH ?{cat_clause}
                    ORDER BY rank
                    LIMIT ?
                    """,
                    [fts_query, *cat_args, bounded_limit * 6],
                ).fetchall()
                for row in rows:
                    _add_score(row, max(0.1, -float(row["rank"])) + 2.0)
            except sqlite3.OperationalError:
                pass

        # 2. Trigram search for 3+ char substrings (Japanese & compound words)
        trigram_terms = [t for t in ([query_str] + tokens) if len(t) >= 3]
        seen_trigrams: set[str] = set()
        for term in trigram_terms[:6]:
            key = term.casefold()
            if key in seen_trigrams:
                continue
            seen_trigrams.add(key)
            escaped = '"' + term.replace('"', '""') + '"'
            try:
                rows = conn.execute(
                    f"""
                    SELECT c.*, bm25(doc_chunks_trigrams, 3.0, 2.0, 1.0) AS rank
                    FROM doc_chunks_trigrams
                    JOIN doc_chunks c ON c.id = doc_chunks_trigrams.rowid
                    WHERE doc_chunks_trigrams MATCH ?{cat_clause}
                    ORDER BY rank
                    LIMIT ?
                    """,
                    [escaped, *cat_args, bounded_limit * 6],
                ).fetchall()
                for row in rows:
                    boost = 4.0 if term == query_str else 2.5
                    _add_score(row, max(0.1, -float(row["rank"])) + boost)
            except sqlite3.OperationalError:
                pass

        # 3. LIKE fallback/boost for short Japanese tokens (e.g. 2-char words) and heading matches
        for token in tokens[:8]:
            pattern = f"%{_escape_like(token)}%"
            rows = conn.execute(
                f"""
                SELECT c.*,
                    (CASE WHEN LOWER(c.title) LIKE LOWER(?) ESCAPE '\\' THEN 5.0 ELSE 0.0 END) +
                    (CASE WHEN LOWER(c.heading) LIKE LOWER(?) ESCAPE '\\' THEN 4.0 ELSE 0.0 END) +
                    (CASE WHEN LOWER(c.content) LIKE LOWER(?) ESCAPE '\\' THEN 1.5 ELSE 0.0 END) AS like_score
                FROM doc_chunks c
                WHERE (
                    LOWER(c.title) LIKE LOWER(?) ESCAPE '\\'
                    OR LOWER(c.heading) LIKE LOWER(?) ESCAPE '\\'
                    OR LOWER(c.content) LIKE LOWER(?) ESCAPE '\\'
                ){cat_clause}
                ORDER BY like_score DESC, c.id ASC
                LIMIT ?
                """,
                [pattern, pattern, pattern, pattern, pattern, pattern, *cat_args, bounded_limit * 6],
            ).fetchall()
            for row in rows:
                _add_score(row, float(row["like_score"]))

    ranked = sorted(
        scored.values(),
        key=lambda item: (-item[0], item[1]["doc_path"], item[1]["chunk_index"]),
    )[:bounded_limit]

    results = [
        {
            "doc_path": row["doc_path"],
            "category": row["category"],
            "title": row["title"],
            "heading": row["heading"],
            "status": row["status"],
            "score": round(score, 3),
            "excerpt": _make_excerpt(row["content"], tokens),
        }
        for score, row in ranked
    ]
    return {
        "query": query_str,
        "petit_version": version,
        "category": category,
        "count": len(results),
        "results": results,
    }
