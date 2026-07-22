"""Runtime model profile selection for PETIT Chat and Agent routes.

Only profile IDs are persisted. API keys remain environment-only and are never
returned to the browser or written to the routing state file.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from . import config

ROUTES = ("chat", "agent")
PROFILE_IDS = ("local", "deepseek_flash", "deepseek_pro")
PROFILE_LABELS = {
    "local": "ローカル LM Studio",
    "deepseek_flash": "DeepSeek V4 Flash",
    "deepseek_pro": "DeepSeek V4 Pro",
}
STATE_PATH = Path(os.getenv("PETIT_MODEL_ROUTING_PATH", config.STORAGE_DIR / "model_routing.json"))
_LOCK = threading.Lock()


class ModelRoutingError(ValueError):
    """Raised when a runtime model selection is invalid or unavailable."""


def _default_profile(route: str) -> str:
    name = "PETIT_CHAT_PROFILE" if route == "chat" else "PETIT_AGENT_PROFILE"
    value = os.getenv(name, "local").strip().lower() or "local"
    return value if value in PROFILE_IDS else "local"


def _read_selection() -> dict[str, str]:
    selection = {route: _default_profile(route) for route in ROUTES}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return selection
    if not isinstance(data, dict):
        return selection
    for route in ROUTES:
        value = str(data.get(route) or "").strip().lower()
        if value in PROFILE_IDS:
            selection[route] = value
    return selection


def _local_target(route: str) -> dict[str, Any]:
    if route == "agent":
        base_url = os.getenv("PETIT_LOCAL_AGENT_BASE_URL", config.AGENT_BASE_URL).strip()
        api_key = os.getenv("PETIT_LOCAL_AGENT_API_KEY", config.AGENT_API_KEY)
        model = os.getenv("PETIT_LOCAL_AGENT_MODEL", config.AGENT_MODEL).strip()
    else:
        base_url = os.getenv("PETIT_LOCAL_CHAT_BASE_URL", config.CHAT_BASE_URL).strip()
        api_key = os.getenv("PETIT_LOCAL_CHAT_API_KEY", config.CHAT_API_KEY)
        model = os.getenv("PETIT_LOCAL_CHAT_MODEL", config.CHAT_MODEL).strip()
    return {
        "provider": "lm_studio",
        "base_url": base_url.rstrip("/"),
        "api_key": api_key,
        "model": model,
        "configured": bool(base_url and model),
        "external": False,
    }


def _deepseek_target(profile: str) -> dict[str, Any]:
    api_key = os.getenv("PETIT_DEEPSEEK_API_KEY", os.getenv("DEEPSEEK_API_KEY", ""))
    base_url = os.getenv("PETIT_DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip().rstrip("/")
    if profile == "deepseek_pro":
        model = os.getenv("PETIT_DEEPSEEK_PRO_MODEL", "deepseek-v4-pro").strip()
    else:
        model = os.getenv("PETIT_DEEPSEEK_FLASH_MODEL", "deepseek-v4-flash").strip()
    return {
        "provider": "deepseek",
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
        "configured": bool(api_key and base_url and model),
        "external": True,
    }


def _target(route: str, profile: str) -> dict[str, Any]:
    if route not in ROUTES:
        raise ModelRoutingError(f"unknown route: {route}")
    if profile == "local":
        target = _local_target(route)
    elif profile in {"deepseek_flash", "deepseek_pro"}:
        target = _deepseek_target(profile)
    else:
        raise ModelRoutingError(f"unknown profile: {profile}")
    return {
        "route": route,
        "profile": profile,
        "label": PROFILE_LABELS[profile],
        **target,
    }


def endpoint(route: str) -> dict[str, Any]:
    """Return the active endpoint including the server-only API key."""
    selection = _read_selection()
    return _target(route, selection[route])


def _public_target(target: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile": target["profile"],
        "label": target["label"],
        "provider": target["provider"],
        "model": target["model"],
        "base_url": target["base_url"],
        "configured": bool(target["configured"]),
        "external": bool(target["external"]),
    }


def public_status() -> dict[str, Any]:
    selection = _read_selection()
    routes: dict[str, Any] = {}
    for route in ROUTES:
        options = []
        for profile in PROFILE_IDS:
            target = _target(route, profile)
            options.append(_public_target(target))
        routes[route] = {
            "selected": selection[route],
            "active": _public_target(_target(route, selection[route])),
            "options": options,
        }
    return {"selections": selection, "routes": routes}


def update_selection(updates: dict[str, str]) -> dict[str, Any]:
    """Validate and persist one or both route selections."""
    if not updates:
        raise ModelRoutingError("ChatまたはAgentの選択を指定してください。")
    with _LOCK:
        selection = _read_selection()
        for route, raw_profile in updates.items():
            if route not in ROUTES:
                raise ModelRoutingError(f"変更できない経路です: {route}")
            profile = str(raw_profile or "").strip().lower()
            if profile not in PROFILE_IDS:
                raise ModelRoutingError(f"利用できないモデル設定です: {profile}")
            target = _target(route, profile)
            if not target["configured"]:
                if target["provider"] == "deepseek":
                    raise ModelRoutingError("DeepSeek APIキーが未設定です。PETIT_DEEPSEEK_API_KEYを.envに追加してください。")
                raise ModelRoutingError(f"{target['label']}の接続設定が未設定です。")
            selection[route] = profile

        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = STATE_PATH.with_suffix(STATE_PATH.suffix + ".tmp")
        temporary.write_text(json.dumps(selection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(STATE_PATH)
    return public_status()
