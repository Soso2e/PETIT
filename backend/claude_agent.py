"""Claude Code agent mode (H3): PETIT works inside PETIT Home with real tools.

Opt-in (``claude_code_agent_mode``). One Turn runs the official ``claude`` once:

- cwd = PETIT Home, ``--restricted`` (no user/project settings, file tools
  confined to Home, settings/git writes refused, Bash only when explicitly opened)
- PETIT Tools over MCP (``backend.petit_mcp``) with a one-Turn token
- PreToolUse hook ``backend.agent_hooks`` draws the L0–L3 line
- ``--resume`` keeps the CLI session per Core Thread; approval resumes the same session

Core stays the source of truth for approvals, receipts, memory and the Turn ledger.
Home edits are committed to Home's git after every Turn (L0 history).
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import (agent_bridge, agent_workspace, claude_code_brain as cc, config, conversation_store as store, db,
               external_brain, petit_home)
from .antigravity_cli_brain import CLIError, invoke

PROVIDER = "claude_agent"
LABEL = "Claude Code（エージェントモード）"
REPO_ROOT = Path(__file__).resolve().parents[1]
FILE_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep"]
HOOK_VERSION = "h4-1"

AGENT_RULES = """
あなたは PETIT Home（作業ディレクトリ）の中で動く。
- Home 内のファイル（memory/ skills/ scratch/ inbox/ outbox/ など）は自由に読み書きしてよい（L0）。覚えたこと・手順は memory/ や skills/ に残してよい。
- AGENTS.md / SOUL.md / USER.md は直接編集しない。変えるときは mcp__petit__update_persona_file に変更後の全文を渡す（Core が差分を見せて承認を取る）。
- タスク・予定・記憶・通知など PETIT のデータは mcp__petit__* の Tool で扱う。Core が正本。
- 外部への送信・push・PR・公開・インストールはしない（L2）。必要ならユーザーに伝える。取り返しのつかない操作と秘密情報には触れない（L3）。
- Tool が承認待ち（awaiting_user_approval）を返したら、それ以上進めずに、何を承認してほしいかを短く伝えて回答を終える。承認前に実行済みと言わない。
- 開発（L1）: list_coding_repositories → open_worktree で Home の worktrees/ に作業用 worktree を作り、その中のファイルを編集する。
  run_worktree_check でテストし、通ったら commit_worktree → push_worktree（petit/ ブランチだけ、確認なし）。
  PR は create_worktree_pull_request（承認つき）。テストの結果は実際の出力どおりに伝え、通っていないものを通ったと言わない。
- 拒否された操作を別の方法で回避しない。
"""


def enabled(data: dict) -> bool:
    return bool(cc.enabled(data) and data.get("claude_code_agent_mode"))


def sandbox_ready() -> bool:
    """Whether Claude Code's OS sandbox can actually run here.

    Without its dependencies the CLI only warns and runs Bash UNSANDBOXED, so
    Core checks them itself and withholds Bash instead.
    """
    if sys.platform.startswith("linux"):
        return bool(shutil.which("bwrap") and shutil.which("socat"))
    if sys.platform == "darwin":
        return bool(shutil.which("sandbox-exec"))
    return False  # Windows: no sandbox for Bash


def bash_allowed(data: dict) -> bool:
    return bool(data.get("claude_code_agent_bash")) and sandbox_ready()


def core_url() -> str:
    return os.getenv("PETIT_CORE_URL", f"http://127.0.0.1:{config.PORT}")


def _quote(parts: list[str]) -> str:
    return subprocess.list2cmdline(parts) if os.name == "nt" else " ".join(shlex.quote(p) for p in parts)


def settings_json(home: Path, *, bash: bool) -> dict:
    hook = _quote([sys.executable, "-m", "backend.agent_hooks"])
    value = {
        "hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": hook, "timeout": 20}]}]},
        "permissions": {"deny": ["WebFetch", "WebSearch", "Task"]},
    }
    if bash:
        # Bash runs only inside Claude Code's OS sandbox: writes limited to cwd, no network.
        value["sandbox"] = {"enabled": True, "autoAllowBashIfSandboxed": True, "allowUnsandboxedCommands": False}
    return value


def mcp_json(token: str) -> dict:
    return {"mcpServers": {"petit": {"type": "stdio", "command": sys.executable, "args": ["-m", "backend.petit_mcp"],
                                     "env": {"PETIT_CORE_URL": core_url(), "PETIT_BRIDGE_TOKEN": token,
                                             "PYTHONPATH": str(REPO_ROOT)}}}}


def command(binary: str, *, model: str, mcp_path: Path, settings_path: Path, system: str, bash: bool,
            resume: str | None) -> list[str]:
    tools = FILE_TOOLS + (["Bash"] if bash else [])
    result = [binary, "-p", "--output-format", "json", "--restricted", "--strict-mcp-config",
              "--mcp-config", str(mcp_path), "--settings", str(settings_path), "--permission-mode", "acceptEdits",
              "--tools", ",".join(tools), "--allowedTools", ",".join(["mcp__petit"] + (["Bash"] if bash else [])),
              "--disable-slash-commands", "--append-system-prompt", system]
    if resume:
        result += ["--resume", resume]
    return result + (["--model", model] if model else [])


def environment(home: Path) -> dict:
    env = cc.environment()
    env.update({"PETIT_HOME": str(home), "PYTHONPATH": str(REPO_ROOT)})
    return env


def parse_output(raw: str) -> dict:
    try:
        value = json.loads(raw)
    except ValueError:
        raise CLIError("invalid_cli_protocol", LABEL + "の出力を検証できませんでした。") from None
    if not isinstance(value, dict) or value.get("type") != "result":
        raise CLIError("invalid_cli_protocol", LABEL + "の出力を検証できませんでした。")
    if value.get("is_error") or value.get("subtype") not in {"success", "error_max_turns"}:
        reason = cc.error_category(str(value.get("result", "")) + " " + str(value.get("subtype", "")))
        raise CLIError(reason, LABEL + "が応答を完了できませんでした。公式CLIの認証・利用枠・モデルを確認してください。")
    session = value.get("session_id")
    return {"reply": str(value.get("result") or ""), "session_id": session if isinstance(session, str) else None,
            "max_turns": value.get("subtype") == "error_max_turns",
            "denials": len(value.get("permission_denials") or []),
            "num_turns": value.get("num_turns") if isinstance(value.get("num_turns"), int) else None}


def _boundary(target: dict, bash: bool) -> str:
    import hashlib
    return hashlib.sha256(store.encode({"model": target.get("model"), "bash": bash, "hook": HOOK_VERSION,
                                        "persona": petit_home.persona(), "home": str(petit_home.root())}).encode()).hexdigest()


def _waiting_session(request_id: str) -> str | None:
    with db.get_connection() as connection:
        row = connection.execute("SELECT payload_json FROM turn_events WHERE request_id=? AND type='claude_agent_session' "
                                 "ORDER BY seq DESC LIMIT 1", (request_id,)).fetchone()
    return json.loads(row[0]).get("session_id") if row else None


def _used(request_id: str) -> list[dict]:
    messages = json.loads(store.load_turn(request_id)["messages_json"] or "[]")
    return [{"name": call["function"]["name"], "arguments": call["function"].get("arguments", "{}")}
            for m in messages for call in m.get("tool_calls", [])]


def run(request_id: str, target: dict, *, messages=None, used_tools=None) -> dict:
    from . import brain, setup_store
    data = setup_store.load()
    try:
        cc.require_production_permission()
    except ValueError as exc:
        raise CLIError(cc.POLICY_REASON, str(exc)) from None
    binary = cc.executable()
    if not binary:
        raise CLIError("not_configured", "公式Claude Code CLIが見つかりません。")
    row = store.load_turn(request_id)
    thread_id = row["thread_id"]
    home = petit_home.ensure()
    bash = bash_allowed(data)
    key = _boundary(target, bash)
    if messages is None:
        saved = agent_workspace.previous(thread_id, PROVIDER, key, request_id)
        resume = saved["session_id"] if saved else None
        if not saved:
            agent_workspace.forget(thread_id, PROVIDER)
    else:
        resume = _waiting_session(request_id)  # continue the session that asked for approval
    # Only the user-data prompt is shared with the Codex bridge; its Tool wording is not.
    _codex_instructions, prompt = external_brain.context(request_id, messages, include_history=resume is None)
    from . import service_sync
    from .petit_prompt import voice_turn_instructions
    system = (petit_home.persona() + brain.INSTRUCTIONS + AGENT_RULES + voice_turn_instructions() +
              "\n運用アラートはCoreが末尾に表示するので本文に重ねて書かない。未解決の事実: " + service_sync.warning())

    def check():
        if store.load_turn(request_id)["cancel_requested"]:
            raise brain.TurnCancelled("取消要求を受け付けました。すでに実行された操作は取り消していません。")
        live = brain.check_provider(store.thread(thread_id))
        if live.get("provider") != cc.PROVIDER or live.get("model") != target.get("model"):
            raise CLIError("provider_changed", "実行中のCLI設定が変わりました。自動再送しません。")

    token = agent_bridge.issue(request_id)
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="petit-claude-agent-", ignore_cleanup_errors=True) as folder:
            mcp_path, settings_path = Path(folder) / "mcp.json", Path(folder) / "settings.json"
            for path, value in ((mcp_path, mcp_json(token)), (settings_path, settings_json(home, bash=bash))):
                path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
                os.chmod(path, 0o600)
            argv = command(binary, model=target.get("model") or "", mcp_path=mcp_path, settings_path=settings_path,
                           system=system, bash=bash, resume=resume)
            try:
                code, output, error = invoke(argv, home, prompt, check, timeout=target.get("agent_timeout_seconds", 900),
                                             label=LABEL, raw_stdin=True, env=environment(home))
            except OSError:
                raise CLIError("cli_start_failed", "Claude Code CLIを起動できません。実行ユーザーと配置を確認してください。") from None
    finally:
        agent_bridge.revoke(token)
        petit_home.commit(home, f"PETIT: {request_id}")  # L0 history; never pushed
    if code and not output.strip():
        raise CLIError(cc.error_category(error), LABEL + "の実行に失敗しました。公式CLIの認証・利用枠・モデルを確認してください。")
    result = parse_output(output.strip())
    brain.check_provider(store.thread(thread_id))
    reply = result["reply"].strip()
    if result["max_turns"]:
        reply = (reply + "\n\n" if reply else "") + "（作業の上限に達したので、ここで止めました。続けるなら「続けて」と言ってください。）"
    if not reply and not store.approvals(request_id):
        raise CLIError("invalid_cli_protocol", LABEL + "から回答を受け取れませんでした。")
    metadata = {"provider": PROVIDER, "model": target.get("model") or "unknown", "kind": "brain", "transport": "cli",
                "resumed": bool(resume), "bash": bash,
                "bash_withheld": bool(data.get("claude_code_agent_bash")) and not bash, "num_turns": result["num_turns"], "denials": result["denials"],
                "latency_seconds": round(time.monotonic() - started, 3), "quota_remaining": "unknown"}
    with db.get_connection() as connection:
        store.event(connection, thread_id, request_id, "claude_agent_session",
                    {"session_id": result["session_id"], "denials": result["denials"]})
    outcome = external_brain.finish(request_id, reply, _used(request_id), metadata)
    if outcome["status"] == "completed" and result["session_id"]:
        agent_workspace.remember(thread_id, PROVIDER, key, result["session_id"], request_id)
    return outcome
