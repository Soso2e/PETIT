"""Bounded, session-scoped image intake; never fetch user supplied URLs."""
from __future__ import annotations

import hashlib
import asyncio
import io
import json
import re
import threading
import time
import warnings
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from . import config, db

router = APIRouter()
MAX_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 20_000_000
MAX_EDGE = 8192
MAX_IMAGES = 4
TTL_SECONDS = 24 * 3600
MAX_SESSION_BYTES = 32 * 1024 * 1024
_LOCK = threading.RLock()
_DECODE_SLOTS = threading.BoundedSemaphore(2)
_STOP = threading.Event()
_CLEANER: threading.Thread | None = None
_FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}


def storage_dir() -> Path:
    return Path(config.STORAGE_DIR) / "attachments"


def owner_key(session_id: str | None) -> str:
    if not session_id or not 16 <= len(session_id) <= 200:
        raise HTTPException(400, "画像には16〜200文字の会話IDが必要です。")
    return hashlib.sha256(session_id.encode()).hexdigest()


def ensure_schema() -> None:
    with db.get_connection() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS chat_attachments (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, created_at REAL NOT NULL,
            metadata_json TEXT NOT NULL, size_bytes INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS chat_attachments_owner ON chat_attachments(owner);
        CREATE TABLE IF NOT EXISTS chat_image_observations (
            conversation_id INTEGER PRIMARY KEY, owner TEXT NOT NULL,
            created_at REAL NOT NULL, observations_json TEXT NOT NULL
        );
        """)


def _path(attachment_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", attachment_id):
        raise HTTPException(404, "画像が見つからないか、期限切れです。")
    return storage_dir() / f"{attachment_id}.img"


def cleanup() -> None:
    with _LOCK:
        ensure_schema()
        cutoff = time.time() - TTL_SECONDS
        with db.get_connection() as conn:
            rows = conn.execute("SELECT id FROM chat_attachments WHERE created_at <= ?", (cutoff,)).fetchall()
            for row in rows:
                _path(row["id"]).unlink(missing_ok=True)
            conn.execute("DELETE FROM chat_attachments WHERE created_at <= ?", (cutoff,))
            conn.execute("DELETE FROM chat_image_observations WHERE created_at <= ?", (cutoff,))
        if storage_dir().exists():
            for path in storage_dir().glob("*.img"):
                if path.stat().st_mtime <= cutoff:
                    path.unlink(missing_ok=True)


def start_cleanup() -> None:
    global _CLEANER
    if _CLEANER and _CLEANER.is_alive():
        return
    cleanup()
    _STOP.clear()

    def loop() -> None:
        import logging
        while not _STOP.wait(60):
            try:
                cleanup()
            except Exception:
                logging.getLogger(__name__).exception("attachment expiry cleanup failed")

    _CLEANER = threading.Thread(target=loop, daemon=True, name="petit-image-expiry")
    _CLEANER.start()


def stop_cleanup() -> None:
    _STOP.set()
    if _CLEANER:
        _CLEANER.join(timeout=2)


def normalize_image(raw: bytes) -> tuple[bytes, dict]:
    if not _DECODE_SLOTS.acquire(blocking=False):
        raise HTTPException(429, "画像の確認が混み合っています。少し待って再試行してください。")
    try:
        return _decode_image(raw)
    finally:
        _DECODE_SLOTS.release()


def _decode_image(raw: bytes) -> tuple[bytes, dict]:
    # Keep text-only startup usable before the optional image dependency is installed.
    from PIL import Image, ImageOps, UnidentifiedImageError
    if not raw or len(raw) > MAX_BYTES:
        raise HTTPException(413, "画像は1枚8MiB以下にしてください。")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                fmt = source.format
                width, height = source.size
                if fmt not in _FORMATS:
                    raise HTTPException(415, "PNG / JPEG / WebPの画像を使用してください。")
                if max(width, height) > MAX_EDGE or width * height > MAX_PIXELS:
                    raise HTTPException(413, "画像は長辺8192px・2000万画素以下にしてください。")
                if getattr(source, "n_frames", 1) != 1:
                    raise HTTPException(415, "アニメーション画像には対応していません。")
                source.verify()
            with Image.open(io.BytesIO(raw)) as source:
                oriented = ImageOps.exif_transpose(source)
                resized = max(oriented.size) > 4096
                oriented.thumbnail((4096, 4096))
                # Construct a fresh image so EXIF, ICC and PNG text cannot survive.
                mode = "RGBA" if "A" in oriented.getbands() or "transparency" in source.info else "RGB"
                converted = oriented.convert(mode)
                clean = Image.new(mode, converted.size)
                clean.paste(converted)
                output = io.BytesIO()
                clean.save(output, format="PNG")
                encoded = output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError,
            Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise HTTPException(415, "画像を読み取れません。形式や破損を確認してください。") from exc
    if len(encoded) > MAX_BYTES:
        raise HTTPException(413, "正規化後の画像が8MiBを超えます。解像度を下げてください。")
    return encoded, {
        "mime_type": "image/png", "original_format": fmt,
        "original_sha256": hashlib.sha256(raw).hexdigest(),
        "original_width": width, "original_height": height,
        "width": clean.width, "height": clean.height,
        "resized": resized, "orientation_normalized": True,
    }


def store(raw: bytes, session_id: str) -> dict:
    owner = owner_key(session_id)
    encoded, metadata = normalize_image(raw)
    with _LOCK:
        cleanup()
        with db.get_connection() as conn:
            used = conn.execute("SELECT COALESCE(SUM(size_bytes),0) FROM chat_attachments WHERE owner=?", (owner,)).fetchone()[0]
            total = conn.execute("SELECT COALESCE(SUM(size_bytes),0) FROM chat_attachments").fetchone()[0]
            count = conn.execute("SELECT COUNT(*) FROM chat_attachments WHERE owner=?", (owner,)).fetchone()[0]
            total_count = conn.execute("SELECT COUNT(*) FROM chat_attachments").fetchone()[0]
            if count >= 32 or total_count >= 1024 or used + len(encoded) > MAX_SESSION_BYTES or total + len(encoded) > 256 * 1024 * 1024:
                raise HTTPException(413, "画像の保存上限です。不要な添付を削除してください。")
            attachment_id = uuid4().hex
            now = time.time()
            metadata.update({"id": attachment_id, "created_at": now, "expires_at": now + TTL_SECONDS})
            storage_dir().mkdir(parents=True, exist_ok=True)
            path = _path(attachment_id)
            path.write_bytes(encoded)
            try:
                conn.execute("INSERT INTO chat_attachments VALUES (?,?,?,?,?)",
                             (attachment_id, owner, now, json.dumps(metadata), len(encoded)))
            except Exception:
                path.unlink(missing_ok=True)
                raise
    return metadata


def load(attachment_id: str, session_id: str | None) -> tuple[bytes, dict]:
    path = _path(attachment_id)
    owner = owner_key(session_id)
    with _LOCK:
        ensure_schema()
        with db.get_connection() as conn:
            row = conn.execute("SELECT * FROM chat_attachments WHERE id=? AND owner=? AND created_at>?",
                               (attachment_id, owner, time.time() - TTL_SECONDS)).fetchone()
        if not row or not path.is_file():
            raise HTTPException(404, "画像が見つからないか、期限切れです。")
        return path.read_bytes(), json.loads(row["metadata_json"])


def save_observations(conversation_id: int, session_id: str, observations: dict) -> None:
    ensure_schema()
    with db.get_connection() as conn:
        conn.execute("INSERT INTO chat_image_observations VALUES (?,?,?,?)",
                     (conversation_id, owner_key(session_id), time.time(), json.dumps(observations, ensure_ascii=False)))


@router.post("/api/attachments", status_code=201)
async def upload(request: Request, x_petit_session: str = Header(default="")) -> dict:
    owner_key(x_petit_session)
    chunks = bytearray()
    try:
        async with asyncio.timeout(30):
            async for chunk in request.stream():
                if len(chunks) + len(chunk) > MAX_BYTES:
                    raise HTTPException(413, "画像は1枚8MiB以下にしてください。")
                chunks.extend(chunk)
    except TimeoutError as exc:
        raise HTTPException(408, "画像の受信がタイムアウトしました。") from exc
    return await run_in_threadpool(store, bytes(chunks), x_petit_session)


@router.get("/api/attachments/{attachment_id}")
def get_image(attachment_id: str, x_petit_session: str = Header(default="")) -> Response:
    raw, metadata = load(attachment_id, x_petit_session)
    return Response(raw, media_type=metadata["mime_type"], headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.delete("/api/attachments/{attachment_id}", status_code=204)
def delete_image(attachment_id: str, x_petit_session: str = Header(default="")) -> Response:
    with _LOCK:
        load(attachment_id, x_petit_session)
        with db.get_connection() as conn:
            conn.execute("DELETE FROM chat_attachments WHERE id=?", (attachment_id,))
            conn.execute("""DELETE FROM chat_image_observations WHERE owner=? AND EXISTS (
                SELECT 1 FROM json_each(observations_json, '$.images')
                WHERE json_extract(value, '$.attachment_id')=?)""", (owner_key(x_petit_session), attachment_id))
        _path(attachment_id).unlink(missing_ok=True)
    return Response(status_code=204)
