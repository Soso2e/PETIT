"""PreToolUse hook for Claude Code agent mode: the L0–L3 line of Concept §4.

Claude Code runs this as ``python -m backend.agent_hooks`` before each tool call
and reads a deny decision from stdout. It is one layer of several: ``--restricted``
already confines file tools to PETIT Home and refuses settings/git writes, and
Core Tools (MCP) carry their own risk and approval.

  L0 PETIT Home       file tools free, except persona files (diff approval) and .git/.claude
  L1 worktrees        PETIT Home/worktrees/<repo>-<id>: edit freely; test/commit/push via Core Tools
  L2 going outside    push / PR / network / publishing -> deny; use approved Core Tools
  L3 irreversible     sudo, deleting outside Home, secrets, main push -> always deny
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path

FILE_TOOLS = {"Read", "Write", "Edit", "MultiEdit", "NotebookEdit", "Glob", "Grep", "LS"}
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
PROTECTED_FILES = {"AGENTS.md", "SOUL.md", "USER.md", "CLAUDE.md"}
PROTECTED_DIRS = {".git", ".claude"}
SECRET_NAMES = re.compile(r"(^|/)(\.env[^/]*|.*\.pem|.*\.key|id_[a-z0-9]+|\.netrc|credentials[^/]*)$", re.I)

PERSONA_REASON = ("人格ファイルは直接書き換えられません。update_persona_file で"
                  "変更後の全文を渡すと、Core が差分を見せて承認を取ります。")
OUTSIDE_REASON = "PETIT Home の外は使えません。リポジトリ・PCファイルの作業は Develop の開発ジョブを使ってください。"
L2_REASON = ("外部への送信・公開・リモート操作はこの場では実行できません（L2）。push は push_worktree、PR は "
             "create_worktree_pull_request（承認つき）など PETIT の Tool を使うか、ユーザーに必要な操作を伝えてください。")
L3_REASON = "取り返しのつかない操作・秘密情報へのアクセスは常に禁止されています（L3）。"

# Commands whose purpose is to reach outside the machine or publish (L2).
L2_COMMANDS = {"curl", "wget", "ssh", "scp", "sftp", "rsync", "nc", "ncat", "telnet", "ftp", "gh", "twine",
               "aws", "gcloud", "az", "kubectl", "docker", "podman"}
L2_SUBCOMMANDS = {("git", "push"), ("git", "remote"), ("git", "fetch"), ("git", "pull"), ("git", "clone"),
                  ("git", "config"), ("git", "submodule"), ("git", "worktree"), ("npm", "publish"), ("npm", "login"), ("pnpm", "publish"),
                  ("yarn", "publish"), ("cargo", "publish"), ("pip", "download"), ("pip", "install"),
                  ("npm", "install"), ("npm", "i"), ("pnpm", "add"), ("yarn", "add"), ("uv", "pip")}
# Commands that are irreversible or escalate (L3).
L3_COMMANDS = {"sudo", "su", "doas", "chown", "chmod", "mkfs", "dd", "shutdown", "reboot", "crontab", "launchctl",
               "systemctl", "reg", "schtasks", "security", "keychain", "passwd", "eval", "exec"}
SAFE_ABSOLUTE = ("/dev/null", "/usr/bin/", "/usr/local/bin/", "/bin/", "/usr/lib/")


def _inside(path: Path, home: Path) -> bool:
    try:
        path.resolve().relative_to(home.resolve())
        return True
    except ValueError:
        return False


def _target(tool_input: dict) -> str | None:
    for key in ("file_path", "notebook_path", "path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _file_decision(tool: str, tool_input: dict, home: Path) -> str | None:
    raw = _target(tool_input)
    if raw is None:
        return None if tool in {"Glob", "Grep", "LS"} else OUTSIDE_REASON
    return path_decision(raw, home, write=tool in WRITE_TOOLS)


def path_decision(raw: str, home: Path, *, write: bool) -> str | None:
    """The L0/L1 file line, shared by this hook and Core's Home file Tools (every Brain)."""
    path = Path(raw).expanduser()
    path = path if path.is_absolute() else home / path
    if not _inside(path, home):
        return OUTSIDE_REASON
    relative = path.resolve().relative_to(home.resolve())
    # .git at any depth (Home and every worktree): no reads either, since .git/config can hold
    # remote credentials. .claude at the top: readable, never writable.
    if ".git" in relative.parts:
        return L3_REASON
    if relative.parts and relative.parts[0] in PROTECTED_DIRS:
        return L3_REASON if write else None
    if SECRET_NAMES.search(relative.as_posix()):
        return L3_REASON
    if write and len(relative.parts) == 1 and relative.parts[0] in PROTECTED_FILES:
        return PERSONA_REASON
    return None


def _segments(command: str) -> list[list[str]]:
    parts = re.split(r"\|\||&&|[;|&\n]|\$\(|`", command)
    words = []
    for part in parts:
        try:
            tokens = shlex.split(part, posix=True)
        except ValueError:
            return [["__unparseable__"]]
        if tokens:
            words.append(tokens)
    return words


def _bash_decision(tool_input: dict, home: Path) -> str | None:
    command = str(tool_input.get("command") or "")
    if not command.strip():
        return None
    if re.search(r"(^|[\s'\"=])(~|\$HOME|\$\{HOME\}|%USERPROFILE%)", command) or ".." in command:
        return OUTSIDE_REASON
    for words in _segments(command):
        if words == ["__unparseable__"]:
            return L3_REASON
        # Skip leading env assignments (FOO=bar cmd).
        while words and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[0]):
            words = words[1:]
        if not words:
            continue
        name = Path(words[0]).name
        if name in L3_COMMANDS:
            return L3_REASON
        if name in {"rm", "rmdir", "shred", "mv"} and any(w.startswith("/") and not _inside(Path(w), home) for w in words[1:]):
            return L3_REASON
        if name in L2_COMMANDS or (len(words) > 1 and (name, words[1]) in L2_SUBCOMMANDS):
            return L2_REASON
        for word in words[1:]:
            if word.startswith("/") and not word.startswith(SAFE_ABSOLUTE) and not _inside(Path(word), home):
                return OUTSIDE_REASON
            if SECRET_NAMES.search(word):
                return L3_REASON
    return None


def decide(tool: str, tool_input: dict, home: Path) -> str | None:
    """Return a deny reason, or None to let Claude Code's own permissions decide."""
    if tool.startswith("mcp__petit__"):
        return None  # Core enforces risk, approval and receipts
    if tool.startswith("mcp__"):
        return L2_REASON
    if tool in FILE_TOOLS:
        return _file_decision(tool, tool_input if isinstance(tool_input, dict) else {}, home)
    if tool == "Bash":
        return _bash_decision(tool_input if isinstance(tool_input, dict) else {}, home)
    if tool in {"TodoWrite", "ExitPlanMode"}:
        return None
    # Web access, subagents and anything new stay closed until explicitly opened.
    return L2_REASON


def main() -> None:
    try:
        event = json.load(sys.stdin)
    except ValueError:
        event = {}
    home = Path(os.environ.get("PETIT_HOME") or event.get("cwd") or ".")
    reason = decide(str(event.get("tool_name") or ""), event.get("tool_input") or {}, home) \
        if isinstance(event, dict) else L3_REASON
    if reason:
        json.dump({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                          "permissionDecisionReason": reason}}, sys.stdout, ensure_ascii=False)
    sys.exit(0)


if __name__ == "__main__":
    main()
