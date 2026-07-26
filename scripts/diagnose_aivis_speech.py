#!/usr/bin/env python3
"""Diagnose PETIT's AivisSpeech connection and save a verified WAV sample."""
from __future__ import annotations

import argparse
import io
import json
import sys
import wave
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend import aivis_speech  # noqa: E402

DEFAULT_TEXT = "こんにちは、音声テストです。"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "storage" / "diagnostics" / "aivis_speech_test.wav"


def _stage_from_error_code(code: str | None, message: str = "") -> str:
    normalized = str(code or "").strip().lower()
    if normalized == "aivis_not_configured":
        return "not_configured"
    if normalized == "aivis_connection_failed":
        return "engine_unreachable"
    if normalized == "aivis_timeout":
        return "request_timeout"
    if normalized in {"aivis_style_unavailable", "aivis_invalid_speakers"}:
        return "speaker_not_found"
    if normalized in {"aivis_empty_audio", "aivis_invalid_response"}:
        return "invalid_audio_response"
    if "/audio_query" in message:
        return "audio_query_failed"
    if "/synthesis" in message:
        return "synthesis_failed"
    return "engine_health_failed"


def validate_wav(audio: bytes) -> dict[str, int | float]:
    """Validate WAV bytes and return safe technical metadata."""
    if len(audio) < 12 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        raise ValueError("AivisSpeechの応答は有効なWAVではありません。")

    try:
        with wave.open(io.BytesIO(audio), "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            sample_rate = wav_file.getframerate()
            frame_count = wav_file.getnframes()
    except (wave.Error, EOFError) as exc:
        raise ValueError("AivisSpeechのWAVを解析できません。") from exc

    if channels <= 0 or sample_width <= 0 or sample_rate <= 0 or frame_count <= 0:
        raise ValueError("AivisSpeechのWAVに再生可能な音声フレームがありません。")

    return {
        "channels": channels,
        "sample_width_bytes": sample_width,
        "sample_rate_hz": sample_rate,
        "frame_count": frame_count,
        "duration_seconds": round(frame_count / sample_rate, 3),
    }


def run_diagnostic(
    *,
    text: str = DEFAULT_TEXT,
    output_path: Path | None = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    """Run engine health, synthesis, WAV validation, and optional file output."""
    status = aivis_speech.status(check_engine=True)
    report: dict[str, Any] = {
        "ok": False,
        "stage": "engine_health",
        "provider": status.get("provider"),
        "configured": bool(status.get("configured")),
        "base_url": status.get("base_url"),
        "configured_style_id": status.get("style_id"),
        "resolved_style_id": status.get("resolved_style_id"),
        "speaker_count": status.get("speaker_count"),
        "text_length": len(text),
    }

    if not status.get("configured"):
        report.update(
            stage="not_configured",
            error_code="aivis_not_configured",
            error="AivisSpeechが設定されていません。",
            retryable=False,
        )
        return report

    if not status.get("available"):
        error_code = str(status.get("error_code") or "aivis_health_failed")
        error = str(status.get("error") or "AivisSpeechの疎通確認に失敗しました。")
        report.update(
            stage=_stage_from_error_code(error_code, error),
            error_code=error_code,
            error=error,
            retryable=bool(status.get("retryable")),
            upstream_status=status.get("upstream_status"),
        )
        return report

    try:
        audio, style_id = aivis_speech.synthesize(text)
    except aivis_speech.AivisSpeechError as exc:
        report.update(
            stage=_stage_from_error_code(exc.code, str(exc)),
            error_code=exc.code,
            error=str(exc),
            retryable=exc.retryable,
            upstream_status=exc.status_code,
        )
        return report

    try:
        wav_info = validate_wav(audio)
    except ValueError as exc:
        report.update(
            stage="invalid_audio_response",
            error_code="invalid_audio_response",
            error=str(exc),
            retryable=False,
            audio_bytes=len(audio),
        )
        return report

    saved_path: str | None = None
    if output_path is not None:
        output = Path(output_path).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(audio)
        saved_path = str(output)

    report.update(
        ok=True,
        stage="complete",
        resolved_style_id=style_id,
        audio_bytes=len(audio),
        wav=wav_info,
        output_path=saved_path,
    )
    return report


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AivisSpeechの疎通・固定短文合成・WAV検証を行います。",
    )
    parser.add_argument("--text", default=DEFAULT_TEXT, help="合成する短いテスト文")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="検証済みWAVの保存先",
    )
    parser.add_argument("--no-write", action="store_true", help="WAVを保存せず診断だけ行う")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = run_diagnostic(
        text=str(args.text),
        output_path=None if args.no_write else args.output,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
