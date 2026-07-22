"""AivisSpeech Engine client used by PETIT's text-to-speech API."""
from __future__ import annotations

from typing import Any

import threading
import time

import httpx

from . import config

_TRANSIENT_STATUS_CODES = {429, 502, 503, 504}
_MAX_REQUEST_ATTEMPTS = 2
_RETRY_DELAY_SECONDS = 0.25
_synthesis_lock = threading.Lock()


class AivisSpeechError(RuntimeError):
    """Raised when AivisSpeech cannot synthesize the requested text."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "aivis_error",
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code


def _base_url() -> str:
    return str(config.TTS_BASE_URL).strip().rstrip("/")


def configured() -> bool:
    return config.TTS_PROVIDER == "aivis" and bool(_base_url())


def _first_style_id(speakers: Any) -> int:
    if not isinstance(speakers, list):
        raise AivisSpeechError("AivisSpeechの話者一覧が不正です。", code="aivis_invalid_speakers")
    for speaker in speakers:
        if not isinstance(speaker, dict):
            continue
        styles = speaker.get("styles")
        if not isinstance(styles, list):
            continue
        for style in styles:
            if not isinstance(style, dict):
                continue
            style_id = style.get("id")
            if isinstance(style_id, int):
                return style_id
    raise AivisSpeechError(
        "AivisSpeechに利用可能な話者スタイルがありません。",
        code="aivis_style_unavailable",
    )


def _response_detail(response: httpx.Response) -> str:
    detail: Any = None
    try:
        payload = response.json()
    except (ValueError, TypeError):
        payload = None

    if isinstance(payload, dict):
        for key in ("detail", "error", "message"):
            if payload.get(key):
                detail = payload[key]
                break
    elif isinstance(payload, str):
        detail = payload

    if detail is None:
        try:
            detail = response.text
        except (httpx.HTTPError, RuntimeError):
            detail = ""

    normalized = " ".join(str(detail or "").split())
    return normalized[:240]


def _request(client: httpx.Client, method: str, path: str, **kwargs: Any) -> httpx.Response:
    url = f"{_base_url()}{path}"
    for attempt in range(_MAX_REQUEST_ATTEMPTS):
        try:
            response = getattr(client, method.lower())(url, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            retryable = status_code in _TRANSIENT_STATUS_CODES
            if retryable and attempt + 1 < _MAX_REQUEST_ATTEMPTS:
                time.sleep(_RETRY_DELAY_SECONDS)
                continue
            detail = _response_detail(exc.response)
            suffix = f": {detail}" if detail else ""
            raise AivisSpeechError(
                f"AivisSpeechの{path}がエラーを返しました（HTTP {status_code}）{suffix}",
                code=f"aivis_http_{status_code}",
                retryable=retryable,
                status_code=status_code,
            ) from exc
        except httpx.TimeoutException as exc:
            if attempt + 1 < _MAX_REQUEST_ATTEMPTS:
                time.sleep(_RETRY_DELAY_SECONDS)
                continue
            raise AivisSpeechError(
                "AivisSpeech Engineの応答がタイムアウトしました。",
                code="aivis_timeout",
                retryable=True,
            ) from exc
        except httpx.RequestError as exc:
            if attempt + 1 < _MAX_REQUEST_ATTEMPTS:
                time.sleep(_RETRY_DELAY_SECONDS)
                continue
            raise AivisSpeechError(
                f"AivisSpeech Engineへ接続できません（{_base_url()}）。Engineの起動状態とPETIT_TTS_BASE_URLを確認してください。",
                code="aivis_connection_failed",
                retryable=True,
            ) from exc
    raise AssertionError("unreachable")


def _resolve_style_id(client: httpx.Client) -> int:
    if config.TTS_STYLE_ID is not None:
        return int(config.TTS_STYLE_ID)
    response = _request(client, "GET", "/speakers")
    return _first_style_id(response.json())


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, float(value)))


def status(*, check_engine: bool = False) -> dict[str, Any]:
    info: dict[str, Any] = {
        "provider": config.TTS_PROVIDER,
        "configured": configured(),
        "base_url": _base_url(),
        "style_id": config.TTS_STYLE_ID,
        "auto_style": config.TTS_STYLE_ID is None,
    }
    if not check_engine or not configured():
        return info

    try:
        with httpx.Client(timeout=config.TTS_TIMEOUT) as client:
            response = _request(client, "GET", "/speakers")
            speakers = response.json()
            resolved_style_id = int(config.TTS_STYLE_ID) if config.TTS_STYLE_ID is not None else _first_style_id(speakers)
        return info | {
            "available": True,
            "resolved_style_id": resolved_style_id,
            "speaker_count": len(speakers) if isinstance(speakers, list) else 0,
        }
    except AivisSpeechError as exc:
        return info | {
            "available": False,
            "error": str(exc),
            "error_code": exc.code,
            "retryable": exc.retryable,
            "upstream_status": exc.status_code,
        }
    except httpx.HTTPError as exc:
        return info | {
            "available": False,
            "error": str(exc),
            "error_code": "aivis_connection_failed",
            "retryable": True,
            "upstream_status": None,
        }
    except (ValueError, TypeError) as exc:
        return info | {
            "available": False,
            "error": str(exc),
            "error_code": "aivis_invalid_response",
            "retryable": False,
            "upstream_status": None,
        }


def synthesize(text: str) -> tuple[bytes, int]:
    spoken = (text or "").strip()
    if not configured():
        raise AivisSpeechError("AivisSpeechが設定されていません。", code="aivis_not_configured")
    if not spoken:
        raise AivisSpeechError("読み上げる文章が空です。", code="aivis_empty_text")
    if len(spoken) > config.TTS_MAX_CHARS:
        raise AivisSpeechError(
            f"読み上げは{config.TTS_MAX_CHARS}文字以内にしてください。",
            code="aivis_text_too_long",
        )

    with _synthesis_lock:
        try:
            with httpx.Client(timeout=config.TTS_TIMEOUT) as client:
                style_id = _resolve_style_id(client)
                query_response = _request(
                    client,
                    "POST",
                    "/audio_query",
                    params={"text": spoken, "speaker": style_id},
                )
                query = query_response.json()
                if not isinstance(query, dict):
                    raise AivisSpeechError(
                        "AivisSpeechの音声クエリが不正です。",
                        code="aivis_invalid_audio_query",
                    )

                query["speedScale"] = _clamp(config.TTS_SPEED_SCALE, 0.5, 2.0)
                query["intonationScale"] = _clamp(config.TTS_INTONATION_SCALE, 0.0, 2.0)
                query["volumeScale"] = _clamp(config.TTS_VOLUME_SCALE, 0.0, 2.0)

                audio_response = _request(
                    client,
                    "POST",
                    "/synthesis",
                    params={"speaker": style_id},
                    json=query,
                    headers={"Accept": "audio/wav"},
                )
                if not audio_response.content:
                    raise AivisSpeechError(
                        "AivisSpeechから音声が返りませんでした。",
                        code="aivis_empty_audio",
                        retryable=True,
                    )
                return bytes(audio_response.content), style_id
        except AivisSpeechError:
            raise
        except httpx.HTTPError as exc:
            raise AivisSpeechError(
                f"AivisSpeech Engineへ接続できません（{_base_url()}）。Engineの起動状態とPETIT_TTS_BASE_URLを確認してください。",
                code="aivis_connection_failed",
                retryable=True,
            ) from exc
        except (TypeError, ValueError) as exc:
            raise AivisSpeechError(
                "AivisSpeechの応答を解析できませんでした。",
                code="aivis_invalid_response",
            ) from exc
