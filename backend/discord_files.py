"""Validated local file staging for Discord Owner-mode file attachments."""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path
from uuid import uuid4

from . import config, development_pc, petit_home, request_context

DEFAULT_MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # 10 MiB (Discord standard limit)
TTL_SECONDS = 3600


def max_attachment_bytes() -> int:
    raw = os.getenv("PETIT_DISCORD_MAX_ATTACHMENT_BYTES", "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return DEFAULT_MAX_ATTACHMENT_BYTES


def storage_dir() -> Path:
    return Path(config.STORAGE_DIR) / "discord_outbox"


def _human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB ({size:,} bytes)"
    return f"{size / (1024 * 1024):.2f} MB ({size:,} bytes)"


def cleanup() -> None:
    root = storage_dir()
    if not root.exists():
        return
    cutoff = time.time() - TTL_SECONDS
    for meta_path in root.glob("*.meta.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            created = float(meta.get("created_at") or 0)
        except (OSError, ValueError, TypeError):
            created = 0
        if created <= cutoff:
            attachment_id = meta_path.name.removesuffix(".meta.json")
            meta_path.unlink(missing_ok=True)
            (root / f"{attachment_id}.bin").unlink(missing_ok=True)


def resolve_file(raw_path: str) -> tuple[Path, int]:
    raw = str(raw_path or "").strip()
    if not raw:
        raise ValueError("送信するファイルのパスを指定してください。")
    candidate = Path(raw)
    if not candidate.is_absolute():
        if ".." in candidate.parts or "~" in raw:
            raise ValueError("対象範囲外または保護されたパスです。")
        candidate = petit_home.root() / candidate
    if candidate.is_dir():
        raise ValueError("フォルダの送信には対応していません。単一のファイルパスを指定してください。")
    try:
        verified = development_pc.host_path(str(candidate), directory=False)
    except FileNotFoundError:
        raise ValueError(f"ファイルが見つかりません: {candidate}") from None
    size = verified.stat().st_size
    limit = max_attachment_bytes()
    if size > limit:
        raise ValueError(f"ファイルサイズが上限（{_human_size(limit)}）を超えています: {_human_size(size)}")
    return verified, size


def preview_send_file(arguments: dict) -> str:
    raw_path = str((arguments or {}).get("path") or "")
    try:
        verified, size = resolve_file(raw_path)
    except ValueError as exc:
        return f"送信できないファイルです: {exc}"
    return (
        "送信先: このチャンネル（サーバー）\n"
        f"ファイル名: {verified.name}\n"
        f"サイズ: {_human_size(size)}\n"
        f"パス: {verified}"
    )


def stage_file(raw_path: str) -> dict:
    request_context.forbid_guild_mode("Discord ファイル送信")
    if request_context.current_source() != "discord" or not request_context.current_is_admin():
        raise ValueError("Discord の管理者会話からのみファイルを送信できます。")
    verified, size = resolve_file(raw_path)
    cleanup()
    root = storage_dir()
    root.mkdir(parents=True, exist_ok=True)
    attachment_id = uuid4().hex
    bin_path = root / f"{attachment_id}.bin"
    meta_path = root / f"{attachment_id}.meta.json"
    shutil.copyfile(verified, bin_path)
    meta = {
        "attachment_id": attachment_id,
        "filename": verified.name,
        "size_bytes": size,
        "path": str(verified),
        "created_at": time.time(),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return {
        "sent": True,
        "attachment_id": attachment_id,
        "filename": verified.name,
        "size_bytes": size,
        "path": str(verified),
    }


def read_attachment(attachment_id: str) -> tuple[bytes, str]:
    if not re.fullmatch(r"[0-9a-f]{32}", str(attachment_id or "")):
        raise FileNotFoundError("添付ファイルが見つかりません。")
    root = storage_dir()
    meta_path = root / f"{attachment_id}.meta.json"
    bin_path = root / f"{attachment_id}.bin"
    if not meta_path.is_file() or not bin_path.is_file():
        raise FileNotFoundError("添付ファイルが見つからないか、期限切れです。")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if time.time() - float(meta.get("created_at") or 0) > TTL_SECONDS:
        meta_path.unlink(missing_ok=True)
        bin_path.unlink(missing_ok=True)
        raise FileNotFoundError("添付ファイルの有効期限が切れました。")
    return bin_path.read_bytes(), str(meta.get("filename") or "attachment.bin")
