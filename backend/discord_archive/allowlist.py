"""Persistent registration allowlist stored locally per archive zone."""
from __future__ import annotations

from copy import deepcopy
import json
import logging
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any

from .policy import ArchivePolicy

log = logging.getLogger("petit.discord_archive")
_lock = threading.RLock()


def allowlist_path(archive_dir: Path | str, zone: str = "personal") -> Path:
    return Path(archive_dir) / f"{zone}.allowlist.json"


def read_state(path: Path, zone: str) -> dict[str, Any]:
    if not path.exists():
        return {"trust_zone": zone, "guilds": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("trust_zone") != zone or not isinstance(data.get("guilds"), dict):
            return {"trust_zone": zone, "guilds": {}}
        return data
    except Exception as exc:
        log.warning("Failed to read allowlist at %s (%s)", path, type(exc).__name__)
        return {"trust_zone": zone, "guilds": {}}


def effective_policy(base_policy: ArchivePolicy, archive_dir: Path | str) -> ArchivePolicy:
    path = allowlist_path(archive_dir, base_policy.zone)
    state = read_state(path, base_policy.zone)
    config = deepcopy(base_policy.config)
    config["_registration_denials"] = {}

    for guild_id, changes in state.get("guilds", {}).items():
        entry = config.setdefault("allow_guilds", {}).setdefault(str(guild_id), {"channels": []})
        allowed = {str(c) for c in entry.get("channels", [])}
        for channel_id, enabled in changes.items():
            c_str = str(channel_id)
            if enabled:
                allowed.add(c_str)
            else:
                allowed.discard(c_str)
                config["_registration_denials"].setdefault(str(guild_id), []).append(c_str)
        entry["channels"] = sorted(allowed)

    return ArchivePolicy(config, zone=base_policy.zone)


_SYNC_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def _write_state_atomic(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_path = tempfile.mkstemp(dir=path.parent, prefix=".allowlist-", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    finally:
        if Path(temp_path).exists():
            Path(temp_path).unlink()


def set_registrations(archive_dir: Path | str, zone: str, guild_id: str | int,
                      channel_ids: list[str | int], enabled: bool) -> None:
    g_id = str(guild_id)
    c_ids = [str(c) for c in channel_ids if str(c).isdigit()]
    if not g_id.isdigit() or not c_ids:
        return

    path = allowlist_path(archive_dir, zone)
    with _lock:
        state = read_state(path, zone)
        entries = state.setdefault("guilds", {}).setdefault(g_id, {})
        for c in c_ids:
            entries[c] = bool(enabled)
        _write_state_atomic(path, state)


def validate_sync_time(sync_time: str) -> str:
    value = str(sync_time or "").strip()
    if not _SYNC_TIME_RE.fullmatch(value):
        raise ValueError("時刻は HH:MM（00:00〜23:59）の形式で指定してください。")
    return value


def get_sync_configs(archive_dir: Path | str, zone: str) -> dict[str, dict[str, Any]]:
    path = allowlist_path(archive_dir, zone)
    with _lock:
        state = read_state(path, zone)
    raw = state.get("sync_schedules")
    if not isinstance(raw, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for g_id, cfg in raw.items():
        if isinstance(cfg, dict):
            result[str(g_id)] = {
                "enabled": bool(cfg.get("enabled", False)),
                "sync_time": str(cfg.get("sync_time") or "05:00"),
            }
    return result


def set_sync_config(archive_dir: Path | str, zone: str, guild_id: str | int,
                    enabled: bool, sync_time: str = "05:00") -> dict[str, Any]:
    g_id = str(guild_id)
    if not g_id.isdigit():
        raise ValueError("guild_id が不正です。")
    valid_time = validate_sync_time(sync_time)

    path = allowlist_path(archive_dir, zone)
    with _lock:
        state = read_state(path, zone)
        schedules = state.setdefault("sync_schedules", {})
        entry = {"enabled": bool(enabled), "sync_time": valid_time}
        schedules[g_id] = entry
        _write_state_atomic(path, state)
    return entry
