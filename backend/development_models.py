"""Development model selection, using account probes without sending prompts."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
import re
import subprocess
import tempfile
import threading
import time

from . import antigravity_cli, antigravity_cli_brain, brain_priority, claude_code_brain, codex_brain, db, setup_store

MODELS = {
    "claude_opus": ("claude_code", "opus", "Claude Opus 5.5"),
    "codex_sol": ("codex", "gpt-6.1-sol", "Codex Sol 6.1"),
    "antigravity_argon": ("antigravity_cli", "gemini-4-argon", "Antigravity Argon"),
    "gemini_flash": ("antigravity_cli", "gemini-3.8-flash", "Gemini 3.8 Flash"),
}
EFFORTS = ("low", "medium", "high")
_lock = threading.Lock()
_cache = None


def invalidate():
    global _cache
    with _lock:
        _cache = None


def parse_agy(raw):
    windows = {}
    for line in raw.splitlines():
        fields = line.strip().split("\t")
        if len(fields) != 4 or not re.fullmatch(r"\d{1,3}%", fields[2]):
            continue
        remaining = int(fields[2][:-1])
        if remaining <= 100:
            windows[fields[0], fields[1]] = remaining
    five = windows.get(("Gemini Models", "Five Hour Limit Remaining"))
    return {
        "antigravity_argon": (five, windows.get(("Gemini 4 Argon", "Gemini 4 Argon Weekly Limit"))),
        "gemini_flash": (five, windows.get(("Gemini Models", "Weekly Limit Remaining"))),
    }


def _agy():
    with tempfile.TemporaryDirectory(prefix="petit-agy-usage-") as cwd:
        proc = subprocess.run([antigravity_cli.executable(), "-p", "/usage"], cwd=cwd, stdin=subprocess.DEVNULL,
                              capture_output=True, encoding="utf-8", errors="replace", timeout=15,
                              env=antigravity_cli_brain.environment(),
                              creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    return {} if proc.returncode else {key: (any(x is not None for x in limits), *limits)
                                       for key, limits in parse_agy(proc.stdout).items()}


def _codex():
    with tempfile.TemporaryDirectory(prefix="petit-codex-usage-") as cwd:
        client = codex_brain.RPC(workspace=cwd)
        try:
            account = client.request("account/read", {"refreshToken": False}, timeout=8).get("account") or {}
            if account.get("type") != "chatgpt":
                return {}
            result = client.request("account/rateLimits/read", timeout=8)
        finally:
            client.close()
    limits = result.get("rateLimits") or {}

    def remaining(key):
        used = (limits.get(key) or {}).get("usedPercent")
        return 100 - used if type(used) in (float, int) and 0 <= used <= 100 else None

    return {"codex_sol": (True, 0 if result.get("ordinaryUsageAllowed") is False else remaining("primary"),
                          remaining("secondary"))}


def _claude():
    auth = claude_code_brain.auth_status()
    if auth["authentication"] != "logged_in" or not auth.get("subscription"):
        return {}
    # PETIT can count its own requests only. The budgets below are routing weights,
    # independent of the Anthropic plan and of usage outside this installation.
    def remaining(hours, budget):
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
        with db.get_connection() as connection:
            counts = dict(connection.execute(
                "SELECT e.kind, COUNT(*) FROM coding_job_events e JOIN coding_jobs j ON j.id=e.job_id "
                "WHERE j.provider='claude_code' AND e.created_at>=? AND e.kind IN ('model_request','usage_limit') GROUP BY e.kind",
                (since,)).fetchall())
        return max(0, 100 - counts.get("model_request", 0) * 100 // budget), bool(counts.get("usage_limit"))

    five, limited = remaining(5, 40)
    weekly, _ = remaining(168, 200)
    return {"claude_opus": (True, 0 if limited else five, weekly)}


PROBES = {"antigravity_cli": _agy, "codex": _codex, "claude_code": _claude}


def _probe(provider):
    try:
        return PROBES[provider]()
    except (OSError, ValueError, TypeError, subprocess.SubprocessError, codex_brain.lmstudio_client.LMStudioError):
        return {}


def usage():
    global _cache
    data = setup_store.load()
    eligible = tuple(p for p in PROBES if brain_priority.permitted(p, data) and brain_priority.target(p, data)["configured"])
    with _lock:
        if _cache and _cache[0] == eligible and time.monotonic() < _cache[1]:
            return _cache[2]
        accounts = {}
        if eligible:
            with ThreadPoolExecutor(max_workers=len(eligible)) as pool:
                for result in pool.map(_probe, eligible):
                    accounts.update(result)
        result = {}
        for key, (provider, _, label) in MODELS.items():
            authenticated, five, weekly = accounts.get(key, (None, None, None))
            result[key] = {"provider": provider, "label": label, "authenticated": authenticated,
                           "five_hour": five, "weekly": weekly, "estimated": key == "claude_opus",
                           "available": provider in eligible and authenticated is True and five != 0 and weekly != 0}
        _cache = (eligible, time.monotonic() + 60, result)
        return result


def select(key, effort, lightweight=False):
    if effort not in EFFORTS or key not in {"auto", *MODELS}:
        raise ValueError("開発モデル・Effortを選択してください。")
    quotas = usage()
    if key == "auto":
        if lightweight and quotas["gemini_flash"]["available"]:
            key = "gemini_flash"
        else:
            candidates = [k for k in MODELS if k != "gemini_flash" and quotas[k]["available"]]
            if not candidates:
                raise ValueError("利用可能な開発CLIがありません。設定の認証と利用枠を確認してください。")

            def score(k):
                item = quotas[k]
                return tuple(-1 if item[field] is None else item[field] for field in ("weekly", "five_hour"))

            key = max(candidates, key=score)
    if not quotas[key]["available"]:
        raise ValueError("選択したCLIの接続・認証または利用枠を確認してください。")
    provider, model, label = MODELS[key]
    return provider, model + "-" + effort if provider == "antigravity_cli" else model, {
        "model_key": key, "label": label, "effort": effort, "quota": quotas[key]}
