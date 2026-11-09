"""PETIT Home: the directory PETIT lives in, and the single source of its persona.

Every Brain (DeepSeek / LM Studio / Codex / Antigravity CLI / Claude Code) reads
the same AGENTS.md / SOUL.md / USER.md, so the persona never splits per entry
point (Concept §3-4). Persona files change only through a Core-approved diff
(Concept §4); memory/, skills/ and scratch/ are free (L0).
"""
from __future__ import annotations

import difflib
import hashlib
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

from .petit_prompt import CORE_SYSTEM_PROMPT

log = logging.getLogger(__name__)

PERSONA_FILES = ("AGENTS.md", "SOUL.md", "USER.md")
MAX_FILE_CHARS = 8000
DIRECTORIES = ("memory", "skills", "inbox", "outbox", "scratch")

_TEMPLATES = {
    "AGENTS.md": "# PETIT — 行動原則\n\n" + CORE_SYSTEM_PROMPT,
    "SOUL.md": (
        "# SOUL — プティの口調と距離感\n\n"
        "<!-- プティの話し方・好み・大切にしていること。そそとプティで育てる。\n"
        "     プティが変更するときは差分を見せて承認を取る（Concept §4）。 -->\n"
    ),
    "USER.md": (
        "# USER — そそについて\n\n"
        "<!-- 生活リズム、苦手なこと、言われ方の好み、続けている習慣など。\n"
        "     プティが追記するときは差分を見せて承認を取る。 -->\n"
    ),
    # Claude Code reads CLAUDE.md; import the shared files instead of duplicating them.
    "CLAUDE.md": "@AGENTS.md\n@SOUL.md\n@USER.md\n",
    "README.md": (
        "# PETIT Home\n\n"
        "プティが住むディレクトリ。設計は PETIT リポジトリの docs/brain/agent-home.md。\n\n"
        "- AGENTS.md / SOUL.md / USER.md: 人格と原則の正本。変更は差分承認。\n"
        "- memory/ skills/ scratch/: プティが自由に使う（L0）。\n"
        "- inbox/ outbox/: 受け取るファイル / 渡すファイル（Git 管理外）。\n"
        "- worktrees/: 登録リポジトリの作業用 worktree（petit/ ブランチ。Home の Git 管理外）。\n"
    ),
    ".gitignore": "inbox/\noutbox/\nworktrees/\n",
}


class HomeError(ValueError):
    pass


def root() -> Path:
    configured = os.getenv("PETIT_HOME", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / "PETIT-Home"


def _git(home: Path, *args: str) -> bool:
    if not shutil.which("git"):
        return False
    try:
        subprocess.run(["git", "-c", "user.name=PETIT", "-c", "user.email=petit@localhost", *args],
                       cwd=home, check=True, capture_output=True, timeout=20)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def ensure() -> Path:
    """Create missing skeleton files. Existing files are never overwritten."""
    home = root()
    if home.is_symlink():
        raise HomeError("PETIT Home にリンクは使用できません。")
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    created = False
    for name in DIRECTORIES:
        (home / name).mkdir(exist_ok=True)
        keep = home / name / ".gitkeep"
        if name in {"memory", "skills", "scratch"} and not keep.exists():
            keep.touch()
    for name, content in _TEMPLATES.items():
        path = home / name
        if path.is_symlink():
            raise HomeError(f"{name} にリンクは使用できません。")
        if not path.exists():
            path.write_text(content, encoding="utf-8")
            created = True
    ignore = home / ".gitignore"
    if ignore.is_file() and "worktrees/" not in ignore.read_text(encoding="utf-8").splitlines():
        # Worktrees are their own git checkouts; Home's history must not swallow them.
        ignore.write_text(ignore.read_text(encoding="utf-8").rstrip("\n") + "\nworktrees/\n", encoding="utf-8")
        created = True
    if not (home / ".git").exists():
        _git(home, "init", "-q")
        created = True
    if created:
        _commit(home, "PETIT Home を初期化")
    return home


def commit(home: Path, message: str) -> bool:
    """Commit whatever changed in Home (L0 history). No-op without git or changes."""
    if not shutil.which("git") or not (home / ".git").exists():
        return False
    try:
        changed = subprocess.run(["git", "status", "--porcelain"], cwd=home, capture_output=True, text=True,
                                 timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return False
    return bool(changed) and _commit(home, message)


def _commit(home: Path, message: str) -> bool:
    return _git(home, "add", "-A") and _git(home, "commit", "-q", "--allow-empty-message", "-m", message)


def _read(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return text[:MAX_FILE_CHARS]


def _meaningful(text: str) -> str:
    """Drop HTML comments so empty templates add nothing to the prompt."""
    body = re.sub(r"<!--.*?-->", "", text, flags=re.S).strip()
    lines = [line for line in body.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    return body if lines else ""


def persona() -> str:
    """The shared persona text. Falls back to the built-in prompt if Home is unusable."""
    try:
        home = ensure()
        parts = []
        for name in PERSONA_FILES:
            path = home / name
            if path.is_file() and not path.is_symlink():
                text = _meaningful(_read(path))
                if text:
                    parts.append(text)
        if parts:
            return "\n\n".join(parts) + "\n"
    except (OSError, HomeError) as exc:
        log.warning("PETIT Home を読めないため既定の人格を使います: %s", type(exc).__name__)
    return CORE_SYSTEM_PROMPT


def read_files() -> dict:
    home = ensure()
    return {"home": str(home), "files": {name: _read(home / name) for name in PERSONA_FILES if (home / name).is_file()}}


def _target(file: str) -> Path:
    if file not in PERSONA_FILES:
        raise HomeError("変更できるのは AGENTS.md / SOUL.md / USER.md だけです。")
    path = ensure() / file
    if path.is_symlink():
        raise HomeError(f"{file} にリンクは使用できません。")
    return path


def diff(file: str, content: str) -> str:
    """Core-computed diff against the current file, shown on the approval card."""
    path = _target(file)
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = difflib.unified_diff(current.splitlines(keepends=True), content.splitlines(keepends=True),
                                 fromfile=f"{file}（現在）", tofile=f"{file}（変更後）")
    return "".join(lines) or "（変更なし）"


def digest(file: str) -> str:
    path = _target(file)
    return hashlib.sha256(path.read_bytes() if path.exists() else b"").hexdigest()


def apply(file: str, content: str, reason: str) -> dict:
    if len(content) > MAX_FILE_CHARS:
        raise HomeError(f"{file} は {MAX_FILE_CHARS} 文字以内にしてください。")
    path = _target(file)
    before = digest(file)
    temp = path.with_name(path.name + ".petit.tmp")
    temp.write_text(content if content.endswith("\n") else content + "\n", encoding="utf-8")
    temp.replace(path)
    committed = _commit(path.parent, f"{file}: {reason.strip()[:120] or '人格ファイルを更新'}")
    return {"updated": True, "file": file, "before_sha256": before, "after_sha256": digest(file),
            "git_committed": committed}
