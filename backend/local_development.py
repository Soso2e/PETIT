"""Bounded, read-only evidence from an explicitly configured local Git checkout.

This adapter never discovers directories, fetches remotes, runs a shell, or writes.
Git evidence reflects local refs only; documents are claims, not verification.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Callable

RunCommand = Callable[[list[str]], bytes]
_DOCUMENT_LIMITS = {"Concept.md": 2400, "PROGRESS.md": 3600, "README.md": 1200}
_MAX_DOCUMENT_BYTES = 128_000
_SECRET_ASSIGNMENT = re.compile(
    r"(?im)\b(api[_-]?key|access[_-]?token|password|secret|private[_-]?key)\b"
    r"(\s*[:=]\s*)([^\s\x60]+)"
)


def _clean(value: str, limit: int = 180) -> str:
    """Remove control characters from untrusted Git/ref metadata."""
    return "".join(c if c.isprintable() else " " for c in value)[:limit]


def _safe_excerpt(value: str, limit: int) -> str:
    text = value.replace("\x00", "").replace("\r\n", "\n")
    text = _SECRET_ASSIGNMENT.sub(r"\1\2[REDACTED]", text)
    # Documents can mention private keys in fenced blocks; never include their body.
    text = re.sub(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        "[REDACTED PRIVATE KEY]", text, flags=re.DOTALL
    )
    return text[:limit]


def _root_document(root: Path, name: str, limit: int) -> dict[str, Any]:
    """Only three hard-coded root documents can be opened; symlinks are excluded."""
    doc = root / name
    try:
        if doc.is_symlink():
            return {"name": name, "status": "excluded_symlink"}
        if not doc.is_file():
            return {"name": name, "status": "missing"}
        size = doc.stat().st_size
        if size > _MAX_DOCUMENT_BYTES:
            return {"name": name, "status": "too_large"}
        with doc.open("rb") as source:
            content = source.read(_MAX_DOCUMENT_BYTES + 1)
        if len(content) > _MAX_DOCUMENT_BYTES or b"\x00" in content:
            return {"name": name, "status": "excluded"}
        raw = content.decode("utf-8-sig", errors="replace")
        excerpt = _safe_excerpt(raw, limit)
        return {"name": name, "status": "ok", "excerpt": excerpt,
                "truncated": len(raw) > len(excerpt), "size_bytes": size}
    except (OSError, UnicodeError):
        return {"name": name, "status": "unavailable"}


def collect_local_development(root: Path, run: RunCommand) -> dict[str, Any]:
    """Inspect Git HEAD, local refs, commits and bounded docs without side effects.

    Caller must already have verified `root` is an allowlisted Git repository root.
    Individual evidence failures are explicit, not converted into 'clean' or 'latest'.
    """
    git = ["git", "-c", "core.fsmonitor=false", "-C", str(root)]

    def read_git(*args: str) -> str | None:
        try:
            return run(git + list(args)).decode("utf-8", errors="replace").strip()
        except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return None

    result: dict[str, Any] = {
        "source": "local_checkout",
        "remote_ref_freshness": "unknown_no_fetch",
        "documents": [_root_document(root, name, limit)
                      for name, limit in _DOCUMENT_LIMITS.items()],
        "branches": [],
        "recent_commits": [],
    }
    head = read_git("rev-parse", "--short=12", "HEAD")
    result["head_sha"] = _clean(head) if head else None
    refs = read_git("for-each-ref", "--count=12", "--sort=-committerdate",
                    "--format=%(refname:short)%09%(objectname:short)%09%(committerdate:iso8601-strict)",
                    "refs/heads")
    if refs is None:
        result["branches_status"] = "unavailable"
    else:
        for line in refs.splitlines()[:12]:
            name, sep, rest = line.partition("\t")
            sha, sep2, timestamp = rest.partition("\t")
            if sep and sep2:
                result["branches"].append({"name": _clean(name), "sha": _clean(sha, 20),
                                           "last_commit_at": _clean(timestamp, 40)})
        result["branches_status"] = "ok"

    history = read_git("log", "-5", "--format=%h%x09%s%x09%cI")
    if history is None:
        result["commits_status"] = "unavailable"
    else:
        for line in history.splitlines()[:5]:
            sha, sep, rest = line.partition("\t")
            subject, sep2, timestamp = rest.partition("\t")
            if sep and sep2:
                result["recent_commits"].append({
                    "sha": _clean(sha, 20),
                    "subject": _safe_excerpt(_clean(subject, 150), 150),
                    "committed_at": _clean(timestamp, 40),
                })
        result["commits_status"] = "ok"

    # Uses existing local tracking refs only. No git fetch, pull, or push.
    upstream = read_git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    result["upstream"] = _clean(upstream) if upstream else None
    if upstream:
        difference = read_git("rev-list", "--left-right", "--count", "HEAD...@{upstream}")
        if difference:
            parts = difference.split()
            if len(parts) == 2 and all(part.isdecimal() for part in parts):
                result["upstream_ahead"] = int(parts[0])
                result["upstream_behind"] = int(parts[1])

    base_ref = next((ref for ref in ("refs/remotes/origin/main", "refs/heads/main")
                     if read_git("rev-parse", "--verify", "--quiet", ref)), None)
    if base_ref:
        difference = read_git("rev-list", "--left-right", "--count", f"HEAD...{base_ref}")
        if difference:
            parts = difference.split()
            if len(parts) == 2 and all(part.isdecimal() for part in parts):
                result["main_comparison"] = {
                    "base": base_ref, "ahead": int(parts[0]), "behind": int(parts[1]),
                    "ref_freshness": "local_only",
                }
    return result
