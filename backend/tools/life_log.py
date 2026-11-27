"""Read the owner's day across Notion daily reports, GitHub, PETIT and Discord (#504)."""
from __future__ import annotations

from .. import life_log
from .registry import tool


@tool(
    name="get_activity_digest",
    description=(
        "本人が指定日に何をしていたかのまとめを返す（読み取り専用）。Notionの日報（Act Schedule）、"
        "GitHubのcommit・PR、PETITとの会話、Discordの本人投稿を横断する。"
        "「昨日なにしてた？」「11/18の進捗」などに使う。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "day": {"type": "string", "default": "yesterday",
                    "description": "YYYY-MM-DD、today、yesterday のいずれか。"},
            "include_entries": {"type": "boolean", "default": False,
                                "description": "まとめの元になった記録の抜粋も返す。"},
        },
        "additionalProperties": False,
    },
)
def get_activity_digest(day: str = "yesterday", include_entries: bool = False):
    digest = life_log.generate(day)
    result = {"day": digest["day"], "status": digest["status"], "text": digest["text"],
              "sources": digest["sources"], "structured": digest.get("payload") or {},
              "inbox_warnings": digest.get("warnings") or []}
    if include_entries:
        result["entries"] = life_log.entries_for(digest["day"])
    return result
