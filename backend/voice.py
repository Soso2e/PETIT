"""Voice / TTS HTTP endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
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
