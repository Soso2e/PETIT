"""Claude Code CLI as a structured Brain step (Concept §4 Executor #3).

The official ``claude`` binary runs headless with every built-in tool, MCP
server, setting source, slash command and session file disabled. It only
returns ``{"content", "tool_calls"}``; PETIT Core validates and executes each
PETIT Tool, including approvals and receipts. User text never goes to argv.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
import time

from . import antigravity_cli as agy, antigravity_cli_brain as shared, conversation_store as store, db

PROVIDER = "claude_code"
LABEL = "Claude Code CLI"
POLICY_REASON = "explicit_connection_required"
POLICY_MESSAGE = "Claude Code CLIは初期設定で明示的に接続してください。環境変数やAPIキーからは有効化しません。"
POLICY_NOTICE = ("Claude Code CLIを自作アプリから呼び出す使い方の契約上の扱いは未確認です（Concept §10）。"
                 "接続は利用者の選択であり、Anthropicの許諾取得を意味しません。")
GUIDE = "https://docs.anthropic.com/en/docs/claude-code/setup"
# Aliases accepted by the official CLI. A catalog, never proof of entitlement.
MODEL_ALIASES = [{"id": "sonnet", "label": "Sonnet（CLIの別名）"}, {"id": "opus", "label": "Opus（CLIの別名）"},
                 {"id": "haiku", "label": "Haiku（CLIの別名）"}]
SYSTEM_PROMPT = ("You are the reasoning step of PETIT. Follow the PETIT contract in the user input. "
                 "Return only the JSON object required by the schema.")
RESPONSE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["content", "tool_calls"],
                   "properties": {"content": {"type": "string"}, "tool_calls": {"type": "array", "maxItems": 12, "items": {
                       "type": "object", "additionalProperties": False, "required": ["name", "arguments"],
                       "properties": {"name": {"type": "string"}, "arguments": {"type": "object"}}}}}}
# CLAUDE_CONFIG_DIR selects the official login location; API keys are never forwarded.
ENV_KEYS = shared.ENV_KEYS | {"CLAUDE_CONFIG_DIR", "XDG_CONFIG_HOME", "LANG", "LC_ALL"}


def environment() -> dict:
    return {k: v for k, v in os.environ.items() if k.upper() in ENV_KEYS}


def executable() -> str | None:
    """Bounded detection of the official native binary; no disk scan.

    Windows npm shims (.cmd/.bat) are rejected: batch argument parsing is not
    a safe boundary even for fixed arguments.
    """
    found = shutil.which("claude")
    if found and not (os.name == "nt" and Path(found).suffix.lower() in {".cmd", ".bat"}):
        return found
    home = Path.home()
    candidates = [home / ".local" / "bin" / ("claude.exe" if os.name == "nt" else "claude"),
                  home / ".claude" / "local" / ("claude.exe" if os.name == "nt" else "claude")]
    return next((str(x) for x in candidates if x.is_file()), None)


def enabled(data: dict) -> bool:
    return bool(data.get("claude_code_enabled") and PROVIDER in data.get("connected", []))


def require_production_permission():
    from . import setup_store
    if not enabled(setup_store.load()):
        raise ValueError(POLICY_MESSAGE)


def status(data: dict | None = None) -> dict:
    on = bool(data and enabled(data))
    return {"provider": PROVIDER, "installed": executable() is not None, "production_enabled": on,
            "reason": None if on else POLICY_REASON, "message": POLICY_NOTICE, "transport": "cli",
            "authentication": "unknown", "model": (data or {}).get("claude_code_model") or "unknown",
            "quota_remaining": "unknown", "tested": False, "guide": GUIDE}


def error_category(text: str) -> str:
    # Classify in memory; provider text is never stored or returned.
    lower = text.lower()
    if "unknown option" in lower:
        return "cli_outdated"
    if any(x in lower for x in ("not logged in", "/login", "invalid api key", "oauth", "authentication")):
        return "authentication_required"
    if any(x in lower for x in ("usage limit", "rate limit", "credit balance", "overloaded")):
        return "usage_limit"
    return agy.error_category(text)


def command(binary: str, model: str = "") -> list[str]:
    result = [binary, "-p", "--output-format", "json", "--tools", "", "--strict-mcp-config",
              "--setting-sources", "", "--disable-slash-commands", "--no-session-persistence",
              "--system-prompt", SYSTEM_PROMPT, "--json-schema", json.dumps(RESPONSE_SCHEMA, separators=(",", ":"))]
    return result + (["--model", model] if model else [])


def parse_output(raw: str, catalog) -> tuple[dict, dict]:
    try:
        value = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, RecursionError):
        raise shared.CLIError("invalid_cli_protocol", LABEL + "の出力を検証できませんでした。") from None
    if not isinstance(value, dict) or value.get("type") != "result":
        raise shared.CLIError("invalid_cli_protocol", LABEL + "の出力を検証できませんでした。")
    if value.get("is_error") or value.get("subtype") != "success":
        reason = error_category(str(value.get("result", "")) + " " + str(value.get("subtype", "")))
        raise shared.CLIError(reason, LABEL + "が応答を完了できませんでした。公式CLIの認証・利用枠・モデルを確認してください。")
    if value.get("permission_denials"):
        raise shared.CLIError("direct_tool_detected", "CLIの直接Toolを検出しました。PETIT Toolへは接続しません。")
    structured = value.get("structured_output")
    response = shared.parse_response(structured if isinstance(structured, dict) else value.get("result", ""),
                                     catalog, label=LABEL, prefix="cc-")
    usage = value.get("usage") if isinstance(value.get("usage"), dict) else {}
    usage = {k: v for k, v in usage.items() if k in {"input_tokens", "output_tokens", "cache_read_input_tokens",
                                                      "cache_creation_input_tokens"} and type(v) is int and v >= 0}
    cost = value.get("total_cost_usd")
    return response, {"provider": PROVIDER, "transport": "cli", "usage": usage or None,
                      # Subscription plans report list-price estimates; this is not a bill.
                      "cost_usd_estimate": cost if isinstance(cost, (int, float)) and cost >= 0 else None,
                      "quota_remaining": "unknown"}


def completion(target: dict, messages: list, catalog, check):
    binary = executable()
    if not binary:
        raise shared.CLIError("not_configured", "公式Claude Code CLIが見つかりません。")
    check()
    prompt = ("PETIT Core request. Follow the PETIT system messages. Respond using the JSON contract below.\n"
              + shared.AGENT_SOURCE.split("---", 2)[-1] + "\nInput data:\n"
              + store.encode({"messages": messages, "tools": catalog.schemas() if hasattr(catalog, "schemas") else catalog}))
    if len(prompt.encode("utf-8")) > 512_000:
        raise shared.CLIError("input_limit", "CLIへ渡す文脈の上限に達しました。")
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="petit-claude-brain-", ignore_cleanup_errors=True) as folder:
        try:
            code, output, error = shared.invoke(command(binary, target.get("model") or ""), Path(folder), prompt, check,
                                                timeout=target.get("timeout_seconds", 120), label=LABEL,
                                                raw_stdin=True, env=environment())
        except OSError:
            raise shared.CLIError("cli_start_failed", "Claude Code CLIを起動できません。実行ユーザーと配置を確認してください。") from None
    if code and not output.strip():
        raise shared.CLIError(error_category(error), LABEL + "の実行に失敗しました。公式CLIの認証・利用枠・モデルを確認してください。")
    response, metadata = parse_output(output.strip(), catalog)
    return response, {**metadata, "model": target.get("model") or "unknown",
                      "latency_seconds": round(time.monotonic() - started, 3)}


def step(request_id: str, target: dict, messages: list, catalog) -> dict:
    from . import brain
    try:
        require_production_permission()
    except ValueError as exc:
        raise shared.CLIError(POLICY_REASON, str(exc)) from None
    row = store.load_turn(request_id)

    def check():
        if store.load_turn(request_id)["cancel_requested"]:
            raise brain.TurnCancelled("取消要求を受け付けました。")
        live = brain.check_provider(store.thread(row["thread_id"]))
        if live.get("provider") != PROVIDER or live.get("model") != target.get("model"):
            raise shared.CLIError("provider_changed", "実行中のCLI設定が変わりました。自動再送しません。")

    response, metadata = completion(target, messages, catalog, check)
    with db.get_connection() as connection:
        store.event(connection, row["thread_id"], request_id, "claude_code_step", metadata)
    return response
