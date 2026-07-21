"""AivisSpeech Engine client used by PETIT's text-to-speech API."""
from __future__ import annotations

from typing import Any

import httpx

from . import config


class AivisSpeechError(RuntimeError):
    """Raised when AivisSpeech cannot synthesize the requested text."""


def _base_url() -> str:
    return str(config.TTS_BASE_URL).strip().rstrip("/")


def configured() -> bool:
    return config.TTS_PROVIDER == "aivis" and bool(_base_url())


def _first_style_id(speakers: Any) -> int:
    if not isinstance(speakers, list):
        raise AivisSpeechError("AivisSpeechの話者一覧が不正です。")
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
    raise AivisSpeechError("AivisSpeechに利用可能な話者スタイルがありません。")


def _resolve_style_id(client: httpx.Client) -> int:
    if config.TTS_STYLE_ID is not None:
        return int(config.TTS_STYLE_ID)
    response = client.get(f"{_base_url()}/speakers")
    response.raise_for_status()
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
            response = client.get(f"{_base_url()}/speakers")
            response.raise_for_status()
            speakers = response.json()
            resolved_style_id = int(config.TTS_STYLE_ID) if config.TTS_STYLE_ID is not None else _first_style_id(speakers)
        return info | {
            "available": True,
            "resolved_style_id": resolved_style_id,
            "speaker_count": len(speakers) if isinstance(speakers, list) else 0,
        }
    except (httpx.HTTPError, ValueError, TypeError, AivisSpeechError) as exc:
        return info | {"available": False, "error": str(exc)}


def synthesize(text: str) -> tuple[bytes, int]:
    spoken = (text or "").strip()
    if not configured():
        raise AivisSpeechError("AivisSpeechが設定されていません。")
    if not spoken:
        raise AivisSpeechError("読み上げる文章が空です。")
    if len(spoken) > config.TTS_MAX_CHARS:
        raise AivisSpeechError(f"読み上げは{config.TTS_MAX_CHARS}文字以内にしてください。")

    try:
        with httpx.Client(timeout=config.TTS_TIMEOUT) as client:
            style_id = _resolve_style_id(client)
            query_response = client.post(
                f"{_base_url()}/audio_query",
                params={"text": spoken, "speaker": style_id},
            )
            query_response.raise_for_status()
            query = query_response.json()
            if not isinstance(query, dict):
                raise AivisSpeechError("AivisSpeechの音声クエリが不正です。")

            query["speedScale"] = _clamp(config.TTS_SPEED_SCALE, 0.5, 2.0)
            query["intonationScale"] = _clamp(config.TTS_INTONATION_SCALE, 0.0, 2.0)
            query["volumeScale"] = _clamp(config.TTS_VOLUME_SCALE, 0.0, 2.0)

            audio_response = client.post(
                f"{_base_url()}/synthesis",
                params={"speaker": style_id},
                json=query,
                headers={"Accept": "audio/wav"},
            )
            audio_response.raise_for_status()
            if not audio_response.content:
                raise AivisSpeechError("AivisSpeechから音声が返りませんでした。")
            return bytes(audio_response.content), style_id
    except AivisSpeechError:
        raise
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        raise AivisSpeechError(f"AivisSpeechがエラーを返しました（HTTP {status_code}）。") from exc
    except httpx.HTTPError as exc:
        raise AivisSpeechError("AivisSpeech Engineへ接続できません。起動状態を確認してください。") from exc
    except (TypeError, ValueError) as exc:
        raise AivisSpeechError("AivisSpeechの応答を解析できませんでした。") from exc
