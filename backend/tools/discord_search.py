"""Tool for searching archived Discord messages and attachments with strict privacy boundaries."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from .. import request_context
from ..discord_archive import (
    ArchivePolicy,
    ArchiveSearch,
    DiscordArchive,
    effective_policy,
)
from .registry import tool

log = logging.getLogger("petit.tools.discord_search")

DEFAULT_ARCHIVE_DIR = Path("storage/archive")


def get_archive_dir() -> Path:
    env_dir = os.environ.get("PETIT_ARCHIVE_DIR")
    if env_dir:
        return Path(env_dir)
    return DEFAULT_ARCHIVE_DIR


def get_searcher(zone: str = "personal") -> ArchiveSearch | None:
    archive_dir = get_archive_dir()
    db_path = archive_dir / f"{zone}.sqlite"
    if not db_path.exists():
        return None

    base_policy = ArchivePolicy({"enabled": True, "trust_zone": zone, "allow_guilds": {}}, zone=zone)
    policy = effective_policy(base_policy, archive_dir)
    archive = DiscordArchive(db_path, zone=zone)
    return ArchiveSearch(archive, policy)


@tool(
    name="search_discord_archive",
    description=(
        "許可されたDiscordチャンネルの過去ログ・会話履歴・添付ファイル（PDF/テキスト等）を検索する。"
        "「Discordで以前話していた〇〇はどうなった？」「Discordの〇〇チャンネルで決定した仕様」などの質問に答える際に使う。"
        "結果には発言日時・発言者・チャンネル・メッセージURLが含まれるため、これらを出典（根拠）として提示すること。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "検索キーワードまたは自然言語の質問"},
            "guild_id": {"type": "string", "description": "特定のDiscordサーバーIDで絞り込む場合（任意）"},
            "channel_id": {"type": "string", "description": "特定のDiscordチャンネルIDで絞り込む場合（任意）"},
            "author_id": {"type": "string", "description": "特定の発言者IDで絞り込む場合（任意）"},
            "since": {"type": "string", "description": "開始日時（ISO 8601形式、任意）"},
            "until": {"type": "string", "description": "終了日時（ISO 8601形式、任意）"},
            "permitted_channels": {
                "type": "array",
                "items": {"type": "string"},
                "description": "検索者が閲覧を許可されているチャンネルID一覧（指定時はこれらに制限、任意）",
            },
            "limit": {"type": "integer", "description": "最大取得件数（1〜20、既定5）", "default": 5},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    risk="safe_read",
)
def search_discord_archive(query: str, limit: int = 5, permitted_channels: list[str] | None = None, **filters) -> dict[str, Any]:
    # Security Boundary Check:
    # If called from Guild Mode, restrict strictly to that Guild ID!
    is_guild = request_context.is_guild_mode()
    current_guild_id = request_context.current_guild_id()

    zone = "personal"
    if is_guild:
        if not current_guild_id:
            # Cannot verify caller guild context -> deny search
            return {
                "error": "permission_denied",
                "message": "Guild context could not be verified.",
                "matches": [],
            }
        # In guild mode, force filter to caller guild
        filters["guild_id"] = str(current_guild_id)
        zone = f"guild_{current_guild_id}"
        searcher = get_searcher(zone=zone)
    else:
        req_gid = filters.get("guild_id")
        if req_gid and get_searcher(zone=f"guild_{req_gid}") is not None:
            zone = f"guild_{req_gid}"
            searcher = get_searcher(zone=zone)
        else:
            searcher = get_searcher(zone="personal")

    if searcher is None:
        return {
            "query": query,
            "count": 0,
            "matches": [],
            "note": "Discordアーカイブがまだ作成されていないか、登録チャンネルがありません。",
        }

    if permitted_channels is not None:
        filters["permitted_channels"] = permitted_channels

    raw_matches = searcher.search(query, limit=limit, **filters)
    matches = []
    for m in raw_matches:
        attachments_info = [
            {
                "filename": a.get("filename"),
                "content_type": a.get("content_type"),
                "size": a.get("size"),
                "url": a.get("url"),
                "extracted_snippet": a.get("extracted_text", "")[:300] if a.get("extracted_text") else None,
            }
            for a in m.get("attachments", [])
        ]
        matches.append(
            {
                "message_id": m.get("message_id"),
                "guild_name": m.get("guild_name"),
                "channel_name": m.get("channel_name"),
                "thread_name": m.get("thread_name"),
                "author_name": m.get("author_name"),
                "content": m.get("content"),
                "created_at": m.get("created_at"),
                "discord_url": m.get("discord_url"),
                "attachments": attachments_info,
                "score": m.get("search_score"),
            }
        )

    return {
        "query": query,
        "count": len(matches),
        "matches": matches,
    }
