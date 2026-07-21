"""Read-only conversational search over Notion pages shared with PETIT."""
from __future__ import annotations

from .. import notion_search
from .registry import tool


@tool(
    name="search_notion",
    description=(
        "Notion接続に共有されたページをキーワード検索し、タイトル・更新日時・プロパティ・本文抜粋・URLを取得する。"
        "読み取り専用で、通常会話では実行しない。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "検索語またはNotion検索を求めるユーザー発話"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 5, "default": 3},
            "max_chars": {"type": "integer", "minimum": 200, "maximum": 2400, "default": 1200},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
)
def search_notion(query: str, limit: int = 3, max_chars: int = 1200):
    return notion_search.search(query=query, limit=limit, max_chars=max_chars)
