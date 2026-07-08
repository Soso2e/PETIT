"""OpenAI-callable weather, news, and background research tools."""
from __future__ import annotations

import json
from typing import Any

from . import db, web_sources
from .tools.registry import tool


@tool(
    name="get_weather",
    description=(
        "指定した場所の天気予報を取得する。"
        "『今日の天気』『明日の東京の天気』のような短い天気確認で使う。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "location": {"type": "string", "description": "場所。例: 東京, Osaka, Sapporo"},
            "date": {"type": "string", "description": "対象日 YYYY-MM-DD。省略可。"},
        },
        "required": ["location"],
    },
)
def get_weather(location: str, date: str | None = None) -> dict[str, Any]:
    return web_sources.get_weather(location, date)


@tool(
    name="search_news",
    description=(
        "ニュースを検索する。"
        "最近のニュースや特定トピックの見出しをすぐ確認したいときに使う。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "検索キーワード"},
            "limit": {"type": "integer", "description": "最大件数。1〜10", "default": 5},
        },
        "required": ["query"],
    },
)
def search_news(query: str, limit: int = 5) -> dict[str, Any]:
    return web_sources.search_news(query, limit)


@tool(
    name="start_background_research",
    description=(
        "ニュース調査や天気確認をバックグラウンドキューに登録する。"
        "ユーザーが『調べておいて』『あとで分かったら教えて』と言った場合や、"
        "会話を止めずに調べたい場合に使う。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "description": "news または weather。一般的な調べ物は news を使う。",
            },
            "query": {"type": "string", "description": "ニュース検索キーワード。kind=news で必須。"},
            "location": {"type": "string", "description": "天気の場所。kind=weather で必須。"},
            "date": {"type": "string", "description": "天気の日付 YYYY-MM-DD。任意。"},
            "limit": {"type": "integer", "description": "ニュース件数。任意。", "default": 5},
        },
        "required": ["kind"],
    },
)
def start_background_research(
    kind: str,
    query: str | None = None,
    location: str | None = None,
    date: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    kind = (kind or "news").strip().lower()
    if kind not in {"news", "weather"}:
        kind = "news"
    payload = {"kind": kind, "query": query, "location": location, "date": date, "limit": limit}
    job_id = db.create_job("background_research", json.dumps(payload, ensure_ascii=False))
    return {
        "queued": True,
        "job_id": job_id,
        "message": "バックグラウンドで調べ始めました。完了したらチャット欄に追加で表示します。",
    }
