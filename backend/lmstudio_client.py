"""Thin client for the LM Studio OpenAI-compatible chat completions endpoint."""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

import httpx

from . import config


log = logging.getLogger(__name__)


class LMStudioError(RuntimeError):
    """Raised when LM Studio is unreachable or returns an error."""


_health_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_HEALTH_CACHE_SECONDS = 30.0
_turn_metrics: ContextVar[dict[str, Any] | None] = ContextVar("petit_turn_metrics", default=None)
_EMPTY_REPLY_FALLBACK = "うまく返答を生成できなかった。もう一度試してみて。"


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


def _record_model_call(route: str, model: str) -> None:
    metrics = _turn_metrics.get()
    if metrics is None:
        return
    metrics["llm_calls"] += 1
    metrics["models"].append(model)
    metrics["endpoint_ids"].append(route)


def _post_completion(
    *,
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    route: str,
) -> dict[str, Any]:
    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=config.LM_TIMEOUT)
        resp.raise_for_status()
    except httpx.ConnectError as exc:
        raise LMStudioError(
            f"{route} モデルに接続できませんでした ({endpoint(route)['base_url']})。"
            "ローカルサーバーが起動しているか確認してください。"
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise LMStudioError(
            f"LM Studio がエラーを返しました: {exc.response.status_code} {exc.response.text[:200]}"
        ) from exc
    except httpx.HTTPError as exc:
        raise LMStudioError(f"LM Studio との通信に失敗しました: {exc}") from exc

    try:
        return resp.json()
    except ValueError as exc:
        raise LMStudioError("LM Studio の応答がJSONではありませんでした。") from exc


def _parse_choice(data: dict[str, Any]) -> dict[str, Any]:
    try:
        choice = data["choices"][0]
        message = dict(choice["message"])
        message["_finish_reason"] = choice.get("finish_reason")
        return message
    except (KeyError, IndexError, TypeError) as exc:
        raise LMStudioError(f"LM Studio の応答を解釈できませんでした: {data}") from exc


def _has_usable_output(message: dict[str, Any]) -> bool:
    content = str(message.get("content") or "").strip()
    return bool(content or message.get("tool_calls"))


def _recovery_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only the system prompt and latest user turn for an empty-output retry."""
    system = next((dict(item) for item in messages if item.get("role") == "system"), None)
    latest_user = next(
        (
            dict(item)
            for item in reversed(messages)
            if item.get("role") == "user" and str(item.get("content") or "").strip()
        ),
        None,
    )
    compact = [item for item in (system, latest_user) if item is not None]
    return compact or messages


def chat_completion(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    temperature: float | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    route: str = "chat",
) -> dict[str, Any]:
    """Call the chat completions endpoint and return the first usable message.

    A model may occasionally return HTTP 200 with an empty assistant content. PETIT
    retries that case once with only the system prompt and latest user turn. If the
    retry is also empty, a stable user-facing fallback is returned instead of asking
    the user to rewrite a valid message.
    """
    if not any(
        message.get("role") == "user" and str(message.get("content") or "").strip()
        for message in messages
    ):
        raise LMStudioError("LLM送信前のmessagesに空でないrole=userがありません。")

    target = endpoint(route)
    selected_model = model or target["model"]
    url = f"{target['base_url'].rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {target['api_key']}"}
    base_payload: dict[str, Any] = {
        "model": selected_model,
        "temperature": config.LM_TEMPERATURE if temperature is None else temperature,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": config.ENABLE_THINKING},
        "max_tokens": max_tokens if max_tokens is not None else config.LIGHT_MAX_TOKENS,
    }
    if tools:
        base_payload["tools"] = tools
        base_payload["tool_choice"] = "auto"

    attempts = (messages, _recovery_messages(messages))
    for retry_count, attempt_messages in enumerate(attempts):
        payload = dict(base_payload)
        payload["messages"] = attempt_messages
        if retry_count:
            payload["temperature"] = 0
            payload["chat_template_kwargs"] = {"enable_thinking": False}

        _record_model_call(route, selected_model)
        try:
            data = _post_completion(url=url, payload=payload, headers=headers, route=route)
            message = _parse_choice(data)
        except LMStudioError:
            if retry_count == 0:
                raise
            log.warning(
                "empty-response retry failed route=%s model=%s retry_count=%s",
                route,
                selected_model,
                retry_count,
                exc_info=True,
            )
            break

        if _has_usable_output(message):
            if retry_count:
                message["_empty_response_recovered"] = True
            return message

        log.warning(
            "empty model response route=%s model=%s finish_reason=%s content_length=%s "
            "reasoning_content_length=%s retry_count=%s raw_message_keys=%s",
            route,
            selected_model,
            message.get("_finish_reason"),
            len(str(message.get("content") or "")),
            len(str(message.get("reasoning_content") or "")),
            retry_count,
            sorted(key for key in message if not key.startswith("_")),
        )

    return {
        "role": "assistant",
        "content": _EMPTY_REPLY_FALLBACK,
        "_finish_reason": "empty_response_fallback",
        "_empty_response_recovered": False,
    }


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
