"""Small web data fetchers for weather and news.

Uses public endpoints and keeps dependencies to the standard library plus httpx.
"""
from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import quote_plus
import xml.etree.ElementTree as ET

import httpx

HTTP_TIMEOUT = 12.0


def get_weather(location: str, target_date: str | None = None) -> dict[str, Any]:
    """Fetch weather from Open-Meteo using its geocoding and forecast APIs."""
    location = (location or "").strip()
    if not location:
        return {"ok": False, "error": "location is required"}

    day = (target_date or date.today().isoformat()).strip()
    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        geo = client.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": location, "count": 1, "language": "ja", "format": "json"},
        )
        geo.raise_for_status()
        matches = geo.json().get("results") or []
        if not matches:
            return {"ok": False, "error": f"location not found: {location}"}

        place = matches[0]
        forecast = client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": "auto",
                "start_date": day,
                "end_date": day,
            },
        )
        forecast.raise_for_status()
        data = forecast.json().get("daily") or {}

    if not data.get("time"):
        return {"ok": False, "error": f"forecast not available for {day}"}

    return {
        "ok": True,
        "location": {
            "name": place.get("name"),
            "country": place.get("country"),
            "admin1": place.get("admin1"),
            "latitude": place.get("latitude"),
            "longitude": place.get("longitude"),
        },
        "date": data["time"][0],
        "weather_code": _first(data, "weather_code"),
        "temperature_max_c": _first(data, "temperature_2m_max"),
        "temperature_min_c": _first(data, "temperature_2m_min"),
        "precipitation_probability_max_percent": _first(data, "precipitation_probability_max"),
    }


def search_news(query: str, limit: int = 5) -> dict[str, Any]:
    """Search Google News RSS and return compact article metadata."""
    query = (query or "").strip()
    if not query:
        return {"ok": False, "error": "query is required"}
    limit = max(1, min(int(limit or 5), 10))
    url = (
        "https://news.google.com/rss/search?q="
        + quote_plus(query)
        + "&hl=ja&gl=JP&ceid=JP:ja"
    )

    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        res = client.get(url, headers={"User-Agent": "PETIT/0.1"})
        res.raise_for_status()

    root = ET.fromstring(res.content)
    items: list[dict[str, str | None]] = []
    for item in root.findall("./channel/item")[:limit]:
        items.append(
            {
                "title": _text(item, "title"),
                "source": _text(item, "source"),
                "published": _text(item, "pubDate"),
                "url": _text(item, "link"),
            }
        )
    return {"ok": True, "query": query, "count": len(items), "items": items}


def format_weather(result: dict[str, Any]) -> str:
    if not result.get("ok"):
        return "天気を取得できませんでした: " + str(result.get("error", "unknown error"))
    place = result.get("location") or {}
    name = " / ".join(x for x in [place.get("name"), place.get("admin1"), place.get("country")] if x)
    return (
        f"{name} の {result.get('date')} の天気です。"
        f"最高 {result.get('temperature_max_c')}℃、最低 {result.get('temperature_min_c')}℃、"
        f"降水確率最大 {result.get('precipitation_probability_max_percent')}% です。"
    )


def format_news(result: dict[str, Any]) -> str:
    if not result.get("ok"):
        return "ニュースを取得できませんでした: " + str(result.get("error", "unknown error"))
    items = result.get("items") or []
    if not items:
        return f"{result.get('query')} のニュースは見つかりませんでした。"
    lines = [f"{result.get('query')} のニュースを見つけました。"]
    for item in items[:5]:
        source = f"（{item.get('source')}）" if item.get("source") else ""
        lines.append(f"- {item.get('title')}{source}\n  {item.get('url')}")
    return "\n".join(lines)


def _first(data: dict[str, Any], key: str) -> Any:
    values = data.get(key) or []
    return values[0] if values else None


def _text(item: ET.Element, tag: str) -> str | None:
    found = item.find(tag)
    return found.text if found is not None else None
