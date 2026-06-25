"""Thin client for the LM Studio OpenAI-compatible chat completions endpoint."""
from __future__ import annotations

from typing import Any

import httpx

from . import config


class LMStudioError(RuntimeError):
    """Raised when LM Studio is unreachable or returns an error."""


def chat_completion(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    temperature: float | None = None,
) -> dict[str, Any]:
    """Call the chat completions endpoint and return the first choice's message.

    Raises LMStudioError on connection/HTTP problems so callers can degrade
    gracefully instead of crashing the server.
    """
    url = f"{config.LM_BASE_URL.rstrip('/')}/chat/completions"
    payload: dict[str, Any] = {
        "model": config.LM_MODEL,
        "messages": messages,
        "temperature": config.LM_TEMPERATURE if temperature is None else temperature,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    headers = {"Authorization": f"Bearer {config.LM_API_KEY}"}

    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=config.LM_TIMEOUT)
        resp.raise_for_status()
    except httpx.ConnectError as exc:
        raise LMStudioError(
            f"LM Studio に接続できませんでした ({config.LM_BASE_URL})。"
            "ローカルサーバーが起動しているか確認してください。"
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise LMStudioError(
            f"LM Studio がエラーを返しました: {exc.response.status_code} {exc.response.text[:200]}"
        ) from exc
    except httpx.HTTPError as exc:
        raise LMStudioError(f"LM Studio との通信に失敗しました: {exc}") from exc

    data = resp.json()
    try:
        return data["choices"][0]["message"]
    except (KeyError, IndexError) as exc:
        raise LMStudioError(f"LM Studio の応答を解釈できませんでした: {data}") from exc


def health() -> dict[str, Any]:
    """Check whether LM Studio is reachable and list available models."""
    url = f"{config.LM_BASE_URL.rstrip('/')}/models"
    headers = {"Authorization": f"Bearer {config.LM_API_KEY}"}
    try:
        resp = httpx.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        models = [m.get("id") for m in resp.json().get("data", [])]
        return {"ok": True, "base_url": config.LM_BASE_URL, "models": models}
    except httpx.HTTPError as exc:
        return {"ok": False, "base_url": config.LM_BASE_URL, "error": str(exc)}
