"""Archive policy and consent boundaries."""
from __future__ import annotations

from copy import deepcopy
import json
import logging
from pathlib import Path
import re
from typing import Any

log = logging.getLogger("petit.discord_archive")


class ArchivePolicy:
    """Consent policy governing which Discord guilds/channels may be archived or searched."""

    def __init__(self, config: dict[str, Any], zone: str = "personal") -> None:
        self.config = deepcopy(config)
        self.enabled = bool(config.get("enabled", True))
        self.zone = str(config.get("trust_zone") or zone)
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", self.zone):
            raise ValueError(f"Invalid trust zone name: {self.zone}")
        self.include_bots = bool(config.get("include_bots", False))
        self.allow_guilds = dict(config.get("allow_guilds", {}))
        self.denials = dict(config.get("_registration_denials", {}))

    def allows(self, guild_id: str | int | None, channel_id: str | int | None,
               thread_id: str | int | None = None, private: bool = False) -> bool:
        if not self.enabled or guild_id is None:
            return False
        g_id = str(guild_id)
        c_id = str(channel_id) if channel_id is not None else ""
        t_id = str(thread_id) if thread_id is not None else None

        allowed = {str(c) for c in self.allow_guilds.get(g_id, {}).get("channels", [])}
        denied = set(str(c) for c in self.denials.get(g_id, []))

        # Check explicit denials
        if t_id and t_id in denied:
            return False
        if not t_id and c_id in denied:
            return False
        if t_id and c_id in denied and t_id not in allowed:
            return False

        if private:
            # Private threads NEVER inherit parent channel consent; they require explicit consent on the thread itself.
            return t_id is not None and t_id in allowed

        # Public threads inherit parent channel consent unless explicitly denied.
        return c_id in allowed or (t_id is not None and t_id in allowed)

    def allows_message(self, row: dict[str, Any]) -> bool:
        return self.allows(
            row.get("guild_id"),
            row.get("channel_id"),
            row.get("thread_id"),
            private=bool(row.get("is_private_thread", False)),
        )

    def sql_scope(self, alias: str = "m") -> tuple[str, list[Any]]:
        pairs = [
            (str(g), str(c))
            for g, data in self.allow_guilds.items()
            for c in data.get("channels", [])
        ] if self.enabled else []

        if not pairs:
            return "0", []

        clauses = []
        params: list[Any] = []
        for g, c in pairs:
            clauses.append(
                f"({alias}.guild_id=? AND (({alias}.channel_id=? AND {alias}.is_private_thread=0) "
                f"OR {alias}.thread_id=?))"
            )
            params.extend([g, c, c])

        sql = "(" + " OR ".join(clauses) + ")"
        for guild, channels in self.denials.items():
            for channel in channels:
                sql += (
                    f" AND NOT ({alias}.guild_id=? AND (COALESCE({alias}.thread_id, '')=? OR "
                    f"({alias}.thread_id IS NULL AND {alias}.channel_id=?)))"
                )
                params.extend([str(guild), str(channel), str(channel)])
        return sql, params
