"""Read-only tool for searching PETIT's own usage and specification database."""
from __future__ import annotations

from typing import Any

from .. import petit_docs
from .registry import tool


@tool(
    name="search_petit_docs",
    description=(
        "PETIT自身の使い方・できること・機能仕様・設定方法・構成・ルールを公式ドキュメントDB"
        "（Concept.md / docs/ / PROGRESS.md）から検索する。"
        "「PETITの使い方」「何ができる？」「○○はどう使う？」「○○の仕様は？」など、"
        "PETIT自身に関する質問に答える前に必ず使う。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "検索したい機能名・使い方・キーワード（例: リマインダー 使い方, 音声会話 設定, Discord Bot）",
            },
            "category": {
                "type": "string",
                "description": "必要時のみ絞り込むカテゴリ（concept, progress, docs, life, dev, voice, ui, channels, core, brain, ops, desktop, vision）",
            },
            "limit": {
                "type": "integer",
                "description": "返す最大件数（1〜10）",
                "default": 5,
            },
        },
        "required": ["query"],
    },
    risk="safe_read",
)
def search_petit_docs(query: str, category: str | None = None, limit: int = 5) -> dict[str, Any]:
    return petit_docs.search_petit_docs(query, category=category, limit=limit)
