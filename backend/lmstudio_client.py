"""Thin client for the LM Studio OpenAI-compatible chat completions endpoint."""
from __future__ import annotations

from typing import Any
import time
from contextlib import contextmanager
from contextvars import ContextVar

import httpx

from . import config


class LMStudioError(RuntimeError):
    """Raised when LM Studio is unreachable or returns an error."""


_health_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_HEALTH_CACHE_SECONDS = 30.0
_turn_metrics: ContextVar[dict[str, Any] | None] = ContextVar("petit_turn_metrics", default=None)


@contextmanager
def observe_turn() -> Any:
    token = _turn_metrics.set({"llm_calls": 0, "models": [], "endpoint_ids": []})
    try:
        yield _turn_metrics.get()
    finally:
        _turn_metrics.reset(token)


def endpoint(route: str) -> dict[str, str]:
    if route == "agent":
        return {"route": "agent", "base_url": config.AGENT_BASE_URL, "api_key": config.AGENT_API_KEY, "model": config.AGENT_MODEL}
    return {"route": "chat", "base_url": config.CHAT_BASE_URL, "api_key": config.CHAT_API_KEY, "model": config.CHAT_MODEL}


def chat_completion(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    temperature: float | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    route: str = "chat",
) -> dict[str, Any]:
    """Call the chat completions endpoint and return the first choice's message.

    Raises LMStudioError on connection/HTTP problems so callers can degrade
    gracefully instead of crashing the server.
    """
    if not any(
        message.get("role") == "user" and str(message.get("content") or "").strip()
        for message in messages
    ):
        raise LMStudioError("LLM送信前のmessagesに空でないrole=userがありません。")

    target = endpoint(route)
    metrics = _turn_metrics.get()
    if metrics is not None:
        metrics["llm_calls"] += 1
        metrics["models"].append(model or target["model"])
        metrics["endpoint_ids"].append(route)
    url = f"{target['base_url'].rstrip('/')}/chat/completions"
    payload: dict[str, Any] = {
        "model": model or target["model"],
        "messages": messages,
        "temperature": config.LM_TEMPERATURE if temperature is None else temperature,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": config.ENABLE_THINKING},
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    payload["max_tokens"] = max_tokens if max_tokens is not None else config.LIGHT_MAX_TOKENS

    headers = {"Authorization": f"Bearer {target['api_key']}"}

    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=config.LM_TIMEOUT)
        resp.raise_for_status()
    except httpx.ConnectError as exc:
        raise LMStudioError(
            f"{route} モデルに接続できませんでした ({target['base_url']})。"
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
        choice = data["choices"][0]
        message = dict(choice["message"])
        message["_finish_reason"] = choice.get("finish_reason")
        return message
    except (KeyError, IndexError) as exc:
        raise LMStudioError(f"LM Studio の応答を解釈できませんでした: {data}") from exc


def health(route: str = "chat") -> dict[str, Any]:
    """Lightweight, cached /models health check for one configured endpoint."""
    now = time.monotonic()
    cached = _health_cache.get(route)
    if cached and now - cached[0] < _HEALTH_CACHE_SECONDS:
        return dict(cached[1])
    target = endpoint(route)
    url = f"{target['base_url'].rstrip('/')}/models"
    headers = {"Authorization": f"Bearer {target['api_key']}"}
    started = time.monotonic()
    try:
        resp = httpx.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        models = [m.get("id") for m in resp.json().get("data", [])]
        result = {"server_ok": True, "base_url": target["base_url"], "model": target["model"], "model_loaded": target["model"] in models, "latency_ms": round((time.monotonic() - started) * 1000), "models": models}
        _health_cache[route] = (now, result)
        return dict(result)
    except httpx.HTTPError as exc:
        result = {"server_ok": False, "base_url": target["base_url"], "model": target["model"], "model_loaded": False, "latency_ms": round((time.monotonic() - started) * 1000), "error": type(exc).__name__}
        _health_cache[route] = (now, result)
        return dict(result)
