"""PETIT Home file Tools (H5): L0/L1 for every Brain, enforced by Core.

Claude Code edits Home with its own file tools behind a hook; Codex, Antigravity
CLI and API Brains have no trustworthy file boundary of their own, so they use
these instead. The line is the same function the hook uses
(``agent_hooks.path_decision``): inside PETIT Home only, no secrets, no ``.git``,
persona files only through ``update_persona_file`` (diff approval).
Worktrees live in Home, so editing them here is L1 development.
"""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Any

from .. import agent_hooks, petit_home
from .registry import tool

MAX_READ = 60_000
MAX_WRITE = 400_000
MAX_LIST = 400
MAX_MATCHES = 200
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next"}


class HomeFileError(ValueError):
    pass


def _resolve(path: str, *, write: bool) -> tuple[Path, Path]:
    home = petit_home.ensure()
    raw = (path or ".").strip() or "."
    reason = agent_hooks.path_decision(raw, home, write=write)
    if reason:
        raise HomeFileError(reason)
    target = Path(raw).expanduser()
    target = (target if target.is_absolute() else home / target).resolve()
    if target.is_symlink():
        raise HomeFileError("リンクは扱えません。")
    return home, target


def _relative(home: Path, path: Path) -> str:
    return path.relative_to(home.resolve()).as_posix() or "."


def _safe(func):
    def wrapper(**kwargs: Any) -> dict:
        try:
            return func(**kwargs)
        except HomeFileError as exc:
            return {"ok": False, "error": str(exc)}
        except UnicodeDecodeError:
            return {"ok": False, "error": "テキストとして読めないファイルです。"}
        except OSError as exc:
            return {"ok": False, "error": f"ファイル操作に失敗しました（{type(exc).__name__}）。"}
    wrapper.__name__ = func.__name__
    return wrapper


def _walk(home: Path, root: Path):
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not (Path(current) / d).is_symlink())
        for name in sorted(files):
            path = Path(current) / name
            if path.is_symlink():
                continue
            relative = _relative(home, path)
            if agent_hooks.path_decision(relative, home, write=False) is None:
                yield relative, path


@tool(name="list_home_files",
      description=("PETIT Home（プティの作業ディレクトリ）のファイル一覧。path で worktrees/<repo> などに絞れる。"
                   "pattern は glob（例: *.py）。Home の外・秘密ファイル・.git は出ない。"),
      parameters={"type": "object", "properties": {"path": {"type": "string", "default": "."},
                                                   "pattern": {"type": "string", "default": "*"}},
                  "additionalProperties": False},
      risk="safe_read")
@_safe
def list_home_files(path: str = ".", pattern: str = "*") -> dict:
    home, root = _resolve(path, write=False)
    if not root.is_dir():
        raise HomeFileError("フォルダが見つかりません。")
    files = [rel for rel, item in _walk(home, root) if fnmatch.fnmatch(item.name, pattern or "*")]
    return {"home": str(home), "files": files[:MAX_LIST], "truncated": len(files) > MAX_LIST}


@tool(name="read_home_file",
      description="PETIT Home のテキストファイルを読む（worktrees/ のコードも可）。大きいファイルは offset/limit 行で分割。",
      parameters={"type": "object", "properties": {"path": {"type": "string"},
                                                   "offset": {"type": "integer", "default": 0, "minimum": 0},
                                                   "limit": {"type": "integer", "default": 400, "minimum": 1, "maximum": 2000}},
                  "required": ["path"], "additionalProperties": False},
      risk="safe_read")
@_safe
def read_home_file(path: str, offset: int = 0, limit: int = 400) -> dict:
    home, target = _resolve(path, write=False)
    if not target.is_file():
        raise HomeFileError("ファイルが見つかりません。")
    lines = target.read_text(encoding="utf-8").splitlines()
    chunk = "\n".join(lines[offset:offset + limit])[:MAX_READ]
    return {"path": _relative(home, target), "offset": offset, "total_lines": len(lines),
            "content": chunk, "more": offset + limit < len(lines)}


@tool(name="search_home_files",
      description="PETIT Home の中を文字列で検索する（大文字小文字は区別しない）。path で worktrees/<repo> などに絞れる。",
      parameters={"type": "object", "properties": {"query": {"type": "string", "minLength": 1},
                                                   "path": {"type": "string", "default": "."}},
                  "required": ["query"], "additionalProperties": False},
      risk="safe_read")
@_safe
def search_home_files(query: str, path: str = ".") -> dict:
    home, root = _resolve(path, write=False)
    needle = query.casefold()
    matches = []
    for rel, item in _walk(home, root if root.is_dir() else root.parent):
        if item.stat().st_size > 2_000_000:
            continue
        try:
            for number, line in enumerate(item.read_text(encoding="utf-8").splitlines(), 1):
                if needle in line.casefold():
                    matches.append({"path": rel, "line": number, "text": line.strip()[:300]})
                    if len(matches) >= MAX_MATCHES:
                        return {"matches": matches, "truncated": True}
        except UnicodeDecodeError:
            continue
    return {"matches": matches, "truncated": False}


def _commit(home: Path, target: Path) -> None:
    # Home history (L0). Worktrees are their own repos: commit them with commit_worktree.
    if "worktrees" not in target.relative_to(home.resolve()).parts[:1]:
        petit_home.commit(home, "PETIT: " + _relative(home, target))


@tool(name="write_home_file",
      description=("PETIT Home のファイルを書く（新規作成・上書き・追記）。memory/ skills/ scratch/ や worktrees/ のコードに使う。"
                   "人格ファイル（AGENTS.md / SOUL.md / USER.md）は update_persona_file を使う。"),
      parameters={"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"},
                                                   "mode": {"type": "string", "enum": ["overwrite", "append"], "default": "overwrite"}},
                  "required": ["path", "content"], "additionalProperties": False},
      risk="low_risk_write")
@_safe
def write_home_file(path: str, content: str, mode: str = "overwrite") -> dict:
    home, target = _resolve(path, write=True)
    if len(content) > MAX_WRITE:
        raise HomeFileError(f"{MAX_WRITE} 文字までです。")
    if target.is_dir():
        raise HomeFileError("フォルダには書けません。")
    target.parent.mkdir(parents=True, exist_ok=True)
    if mode == "append" and target.exists():
        content = target.read_text(encoding="utf-8") + content
    temp = target.with_name(target.name + ".petit.tmp")
    temp.write_text(content, encoding="utf-8")
    temp.replace(target)
    _commit(home, target)
    return {"written": True, "path": _relative(home, target), "chars": len(content)}


@tool(name="edit_home_file",
      description="PETIT Home のファイルの一部を置き換える。old_text はファイル内でちょうど1回だけ現れる文字列にする。",
      parameters={"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string", "minLength": 1},
                                                   "new_text": {"type": "string"}},
                  "required": ["path", "old_text", "new_text"], "additionalProperties": False},
      risk="low_risk_write")
@_safe
def edit_home_file(path: str, old_text: str, new_text: str) -> dict:
    home, target = _resolve(path, write=True)
    if not target.is_file():
        raise HomeFileError("ファイルが見つかりません。")
    current = target.read_text(encoding="utf-8")
    count = current.count(old_text)
    if count != 1:
        raise HomeFileError(f"old_text の一致が {count} 件です。1件だけ一致するように範囲を広げてください。")
    temp = target.with_name(target.name + ".petit.tmp")
    temp.write_text(current.replace(old_text, new_text, 1), encoding="utf-8")
    temp.replace(target)
    _commit(home, target)
    return {"edited": True, "path": _relative(home, target)}
