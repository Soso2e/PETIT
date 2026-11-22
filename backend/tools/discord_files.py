"""Discord Owner-mode file attachment tool."""
from __future__ import annotations

from .. import discord_files, request_context
from .registry import tool


def _needs_server_confirmation() -> bool:
    return bool(request_context.current_discord_guild_id())


@tool(
    name="send_discord_file",
    description=(
        "PC上の単一ファイルを現在のDiscordチャンネルまたはDMへ添付送信する（Ownerモード専用）。"
        "フォルダや秘密ファイル（.env/.ssh/.git/鍵類）は送信できない。"
        "サーバーのチャンネルでは送信前にパス確認の承認ボタンが出る。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "minLength": 1,
                "maxLength": 1000,
                "description": "送信するファイルの絶対パス（または PETIT Home 相対パス）。フォルダは指定不可。",
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    },
    risk="confirm_write",
    preview=discord_files.preview_send_file,
    confirm_if=_needs_server_confirmation,
)
def send_discord_file(path: str) -> dict:
    return discord_files.stage_file(path)
