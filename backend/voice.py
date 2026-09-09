"""Voice / TTS HTTP endpoints."""
from __future__ import annotations

from typing import Any

import httpx
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from . import aivis_speech, config

router = APIRouter()


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=config.TTS_MAX_CHARS)


@router.get("/api/tts/status")
def tts_status() -> dict[str, Any]:
    return aivis_speech.status(check_engine=True)


@router.post("/api/tts")
def synthesize_speech(payload: TTSRequest) -> Response:
    try:
        audio, style_id = aivis_speech.synthesize(payload.text)
    except aivis_speech.AivisSpeechError as exc:
        error_payload: dict[str, Any] = {
            "error": str(exc),
            "error_code": exc.code,
            "retryable": exc.retryable,
            "upstream_status": exc.status_code,
        }
        if exc.retry_after_seconds is not None:
            error_payload["retry_after_seconds"] = exc.retry_after_seconds
        return JSONResponse(error_payload, status_code=503)
    return Response(
        content=audio,
        media_type="audio/wav",
        headers={
            "Cache-Control": "no-store",
            "X-PETIT-TTS-Provider": "aivis",
            "X-PETIT-TTS-Style-ID": str(style_id),
        },
    )


STT_MAX_BYTES = 8 * 1024 * 1024
STT_MEDIA_TYPES = {"audio/webm": "webm", "audio/mp4": "m4a", "audio/ogg": "ogg", "audio/wav": "wav"}


def _stt_configured() -> bool:
    try:
        url = urlsplit(config.STT_URL)
        return bool(url.hostname and not url.username and not url.password and not url.fragment and
                    (url.scheme == "https" or (url.scheme == "http" and url.hostname in
                     {"localhost", "127.0.0.1", "::1"})))
    except ValueError:
        return False


@router.get("/api/stt/status")
def stt_status() -> dict[str, Any]:
    # Configuration only: never expose endpoint credentials or claim upstream health.
    return {"configured": _stt_configured(), "max_bytes": STT_MAX_BYTES, "max_seconds": 60}


@router.post("/api/stt")
async def transcribe_speech(request: Request) -> Response:
    def error(message: str, code: str, status: int) -> JSONResponse:
        return JSONResponse({"error": message, "error_code": code}, status_code=status,
                            headers={"Cache-Control": "no-store"})

    if not _stt_configured():
        return error("録音認識は未設定です。PETIT_STT_URLにWhisper互換URL（HTTPSまたはlocalhost）を設定して再起動してください。",
                     "stt_not_configured", 503)
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type not in STT_MEDIA_TYPES:
        return error("この録音形式には対応していません。", "unsupported_audio", 415)
    audio = bytearray()
    async for chunk in request.stream():
        if len(audio) + len(chunk) > STT_MAX_BYTES:
            return error("録音が大きすぎます。60秒以内で録音し直してください。", "audio_too_large", 413)
        audio.extend(chunk)
    if not audio:
        return error("録音が空です。もう一度話してください。", "empty_audio", 400)
    headers = {"Authorization": f"Bearer {config.STT_API_KEY}"} if config.STT_API_KEY else {}
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            response = await client.post(config.STT_URL, headers=headers,
                files={"file": ("speech." + STT_MEDIA_TYPES[media_type], bytes(audio), media_type)},
                data={"model": config.STT_MODEL, "language": "ja", "response_format": "json"})
        if not 200 <= response.status_code < 300:
            return error(f"音声認識サーバーがエラーを返しました（HTTP {response.status_code}）。設定と起動状態を確認してください。",
                         "stt_upstream_error", 502)
        data = response.json()
        text = data.get("text") if isinstance(data, dict) else None
        if not isinstance(text, str) or len(text) > 12000:
            raise ValueError("invalid transcript")
    except httpx.TimeoutException:
        return error("音声認識が時間切れになりました。短く録音して再試行してください。", "stt_timeout", 504)
    except httpx.HTTPError:
        return error("音声認識サーバーへ接続できません。URLと起動状態を確認してください。", "stt_unavailable", 503)
    except ValueError:
        return error("音声認識サーバーの応答形式が不正です。", "invalid_transcript", 502)
    return JSONResponse({"text": text.strip()}, headers={"Cache-Control": "no-store"})
