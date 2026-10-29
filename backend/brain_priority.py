"""Ordered, consent-gated runtime selection. Never replay an Agent after a Tool."""
from __future__ import annotations

from contextvars import ContextVar
import json
import shutil

from . import setup_store as settings, conversation_store as store, db, lmstudio_client

_active: ContextVar[dict | None] = ContextVar("petit_brain_target", default=None)


def enabled() -> bool:
    return settings.load()["brain_enabled"]


def target(provider: str, data: dict | None = None) -> dict:
    data = settings.load() if data is None else data
    if provider == "antigravity_cli":
        from .antigravity_cli import executable
        return {"provider": "antigravity_cli", "profile": "antigravity_cli", "label": "Antigravity CLI", "external": True,
                "model": data["antigravity_cli_model"], "base_url": "", "api_key": "", "timeout_seconds": 90,
                "configured": bool(executable())}
    if provider == "codex":
        from .codex_brain import executable
        return {"provider": "codex", "profile": "codex", "label": "Codex（ChatGPT）", "external": True,
                "model": data["codex_model"], "base_url": "", "configured": bool(executable()), "api_key": ""}
    if provider == "antigravity":
        from .antigravity_brain import installed
        from .model_routing import sdk_local_url
        local = data["antigravity_auth"] == "local"
        key = data["secrets"].get("antigravity_key", "")
        return {"provider": "antigravity_sdk", "profile": "antigravity", "label": "Antigravity SDK", "external": not local,
                "model": data["antigravity_model"], "base_url": data["antigravity_url"] if local else "https://generativelanguage.googleapis.com",
                "api_key": key, "auth_mode": data["antigravity_auth"], "timeout_seconds": 90, "core_tools": True,
                "configured": bool(installed() and data["antigravity_model"] and (sdk_local_url(data["antigravity_url"]) if local else key))}
    if provider == "deepseek":
        import os
        key = data["secrets"].get("deepseek_key", os.getenv("PETIT_DEEPSEEK_API_KEY", os.getenv("DEEPSEEK_API_KEY", "")))
        return {"provider": "deepseek", "profile": "deepseek", "label": "DeepSeek", "external": True,
                "model": data["deepseek_model"], "base_url": "https://api.deepseek.com", "api_key": key, "configured": bool(key)}
    raise ValueError("unknown_provider")


def permitted(provider: str, data: dict, privacy="standard") -> bool:
    if data.get("brain_transport") == "cli_only" and provider not in {"codex", "antigravity_cli"}:
        return False
    if provider == "antigravity_cli" and not data.get("antigravity_cli_enabled"):
        return False
    if provider not in data["connected"]:
        return False
    paid = provider == "deepseek" or (provider == "antigravity" and data["antigravity_auth"] != "local")
    if paid and provider not in data["paid_allowed"]:
        return False
    if privacy == "local_only" and (provider != "antigravity" or data["antigravity_auth"] != "local"):
        return False
    return True


def current() -> dict | None:
    active = _active.get()
    if active is not None:
        data = settings.load()
        if (not data["brain_enabled"] and not active.get("_connection_test")) or not permitted(active["profile"], data):
            raise lmstudio_client.LMStudioError("実行中のAI接続または費用許可が解除されました。")
        live = target(active["profile"])
        if any(live.get(k) != active.get(k) for k in ("provider", "model", "base_url", "auth_mode", "api_key")):
            raise lmstudio_client.LMStudioError("実行中のAI設定が変更されました。自動再送しません。")
    return active


def diagnostic(request_id, provider, state, reason=None):
    row = store.load_turn(request_id)
    with db.get_connection() as c:
        store.event(c, row["thread_id"], request_id, "brain_selection", {"provider_id": provider, "state": state, "reason": reason})


def run(request_id, execute, *, messages=None, used_tools=None):
    data = settings.load()
    row = store.load_turn(request_id)
    privacy = store.thread(row["thread_id"])["privacy"]
    candidates = list(data["priority"])
    if messages is not None:
        with db.get_connection() as c:
            selected = c.execute("SELECT payload_json FROM turn_events WHERE request_id=? AND type='brain_selection' ORDER BY seq DESC LIMIT 1", (request_id,)).fetchone()
        if not selected:
            raise lmstudio_client.LMStudioError("既存依頼のProviderを確認できません。自動切替はしません。")
        candidates = [json.loads(selected[0])["provider_id"]]
    previous = None
    for provider in candidates:
        if not permitted(provider, data, privacy):
            continue
        destination = target(provider)
        if not destination["configured"]:
            diagnostic(request_id, provider, "unavailable", "not_configured")
            previous = "not_configured"
            continue
        diagnostic(request_id, provider, "selected", previous)
        destination["fallback_reason"] = previous
        token = _active.set(destination)
        try:
            return execute(request_id, messages=messages, used_tools=used_tools)
        except lmstudio_client.LMStudioError as exc:
            with db.get_connection() as c:
                effect = c.execute("SELECT 1 FROM effect_receipts WHERE request_id=? LIMIT 1", (request_id,)).fetchone()
                activity = c.execute("SELECT 1 FROM turn_events WHERE request_id=? AND type='external_tool_started' LIMIT 1", (request_id,)).fetchone()
                pending = c.execute("SELECT 1 FROM turn_approvals WHERE request_id=? LIMIT 1", (request_id,)).fetchone()
            if messages is not None or effect or activity or pending or store.load_turn(request_id)["messages_json"] or store.load_turn(request_id)["cancel_requested"]:
                raise
            cause = exc.__cause__
            response = getattr(cause, "response", None)
            status = getattr(response, "status_code", None)
            reason = getattr(exc, "reason", None) or ("authentication_expired" if status in (401, 402, 403) else "usage_limit" if status == 429 else "connection_or_runtime_failure")
            diagnostic(request_id, provider, "failed", reason)
            previous = reason
            # No Tool has begun. Previous process is closed before the next runtime starts.
            with db.get_connection() as c:
                c.execute("UPDATE turns SET provider_key=NULL WHERE request_id=?", (request_id,))
        finally:
            _active.reset(token)
    if data.get("brain_transport") == "cli_only":
        raise lmstudio_client.LMStudioError("利用可能なCLI Brainがありません。CLIの導入・公式ログイン・接続テストを確認してください。CLIのみの設定ではSDK/APIへ切り替えません。")
    raise lmstudio_client.LMStudioError("利用可能なAIがありません。設定で認証・モデル・費用許可を確認してください。")


def public_status():
    data = settings.load()
    options = []
    for provider in data["priority"]:
        item = target(provider)
        options.append({"id": provider, "configured": item["configured"], "model": item["model"],
                        "transport": "cli" if provider in {"codex", "antigravity_cli"} else "sdk" if provider == "antigravity" else "api",
                        "connected": provider in data["connected"], "permitted": permitted(provider, data)})
    with db.get_connection() as c:
        exists = c.execute("SELECT 1 FROM sqlite_master WHERE name='turn_events'").fetchone()
        last = c.execute("SELECT payload_json,created_at FROM turn_events WHERE type='brain_selection' ORDER BY seq DESC LIMIT 1").fetchone() if exists else None
    return {"options": options, "latest": ({**json.loads(last[0]), "at": last[1]} if last else None)}
