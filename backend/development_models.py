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
    "claude_sonnet": ("claude_code", "sonnet", "Claude Sonnet 5.5"),
    "claude_opus": ("claude_code", "opus", "Claude Opus 5.5"),
    "codex_sol": ("codex", "gpt-6.1-sol", "Codex Sol 6.1"),
    "antigravity_hydrogen": ("antigravity_cli", "gemini-4-hydrogen", "Antigravity Hydrogen"),
    "gemini_flash": ("antigravity_cli", "gemini-3.8-flash", "Gemini 3.8 Flash"),
}
EFFORTS = ("low", "medium", "high")
# Probing three CLIs takes seconds. A recent result is served as is; an older one is still served
# at once while a single background probe replaces it, so creating a job does not wait for the CLIs.
FRESH_SECONDS = 60
STALE_SECONDS = 3600
_lock = threading.Lock()
_probing = threading.Lock()
_cache = None  # (eligible providers, time.monotonic() of the probe, result)
_generation = 0
_refreshing = False


def invalidate():
    global _cache, _generation
    with _lock:
        _cache = None
        _generation += 1


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
        "antigravity_hydrogen": (five, windows.get(("Gemini Models", "Weekly Limit Remaining"))),
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
    limits = (True, 0 if limited else five, weekly)
    return {"claude_opus": limits, "claude_sonnet": limits}


PROBES = {"antigravity_cli": _agy, "codex": _codex, "claude_code": _claude}


def _probe(provider):
    try:
        return PROBES[provider]()
    except (OSError, ValueError, TypeError, subprocess.SubprocessError, codex_brain.lmstudio_client.LMStudioError):
        return {}


def _collect(eligible):
    accounts = {}
    if eligible:
        with ThreadPoolExecutor(max_workers=len(eligible)) as pool:
            for result in pool.map(_probe, eligible):
                accounts.update(result)
    result = {}
    for key, (provider, _, label) in MODELS.items():
        authenticated, five, weekly = accounts.get(key, (None, None, None))
        result[key] = {"provider": provider, "label": label, "authenticated": authenticated,
                       "five_hour": five, "weekly": weekly, "estimated": provider == "claude_code",
                       "available": provider in eligible and authenticated is True and five != 0 and weekly != 0}
    return result


def _cached(eligible, limit):
    """The cached result for these providers if it is younger than ``limit`` seconds. Call with _lock held."""
    if _cache and _cache[0] == eligible and time.monotonic() - _cache[1] < limit:
        return _cache[2]
    return None


def _probe_and_store(eligible, generation):
    global _cache
    result = _collect(eligible)
    with _lock:
        # An invalidation during the probe (settings change, usage limit) wins over this result.
        if generation == _generation:
            _cache = (eligible, time.monotonic(), result)
    return result


def _refresh(eligible, generation):
    global _refreshing
    try:
        with _probing:
            _probe_and_store(eligible, generation)
    except Exception:  # noqa: BLE001 - the stale value stays until the next request probes again
        pass
    finally:
        with _lock:
            _refreshing = False


def usage(*, allow_stale=True):
    global _refreshing
    data = setup_store.load()
    eligible = tuple(p for p in PROBES if brain_priority.permitted(p, data) and brain_priority.target(p, data)["configured"])
    with _lock:
        fresh = _cached(eligible, FRESH_SECONDS)
        if fresh is not None:
            return fresh
        stale = _cached(eligible, STALE_SECONDS) if allow_stale else None
        if stale is not None:
            if not _refreshing:
                _refreshing = True
                threading.Thread(target=_refresh, args=(eligible, _generation), daemon=True,
                                 name="petit-development-usage").start()
            return stale
        generation = _generation
    with _probing:
        with _lock:
            # Another caller may have finished the same probe while this one waited.
            fresh = _cached(eligible, FRESH_SECONDS)
            if fresh is not None:
                return fresh
        return _probe_and_store(eligible, generation)


def select(key, effort, lightweight=False):
    if effort not in EFFORTS or key not in {"auto", *MODELS}:
        raise ValueError("開発モデル・Effortを選択してください。")
    quotas = usage()
    try:
        return _choose(key, effort, lightweight, quotas)
    except ValueError:
        with _lock:
            served_stale = bool(_cache and _cache[2] is quotas and time.monotonic() - _cache[1] >= FRESH_SECONDS)
        if not served_stale:
            raise
        # An older result must not turn a request down: a quota window may have reset since. Ask the CLIs now.
        return _choose(key, effort, lightweight, usage(allow_stale=False))


def _choose(key, effort, lightweight, quotas):
    if key == "auto":
        if quotas["antigravity_hydrogen"]["available"]:
            key = "antigravity_hydrogen"
        elif lightweight and quotas["gemini_flash"]["available"]:
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
