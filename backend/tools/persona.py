"""Persona files in PETIT Home. Changes are shown as a Core-computed diff and approved."""
from __future__ import annotations

from typing import Any

from .. import petit_home
from .registry import tool


@tool(
    name="get_persona",
    description=("PETIT Home の人格ファイル（AGENTS.md 行動原則 / SOUL.md 口調と距離感 / USER.md ユーザーについて）"
                 "の現在の本文を読む。人格ファイルを変更する提案の前に必ず読む。"),
    parameters={"type": "object", "properties": {}, "additionalProperties": False},
    risk="safe_read",
)
def get_persona() -> dict[str, Any]:
    try:
        return petit_home.read_files()
    except (OSError, petit_home.HomeError) as exc:
        return {"error": str(exc) if isinstance(exc, petit_home.HomeError) else "PETIT Home を読めませんでした。"}


def _preview(arguments: dict[str, Any]) -> str:
    reason = str(arguments.get("reason") or "").strip()
    return ("理由: " + (reason or "（未記入）") + "\n\n" +
            petit_home.diff(str(arguments.get("file") or ""), str(arguments.get("content") or "")))


@tool(
    name="update_persona_file",
    description=("PETIT Home の人格ファイル1つを、変更後の全文で置き換える。ユーザーが口調・好み・自分についての情報を"
                 "教えた、または変えてほしいと言ったときに使う。get_persona で現在の本文を読み、変えない部分はそのまま残す。"
                 "実行前に Core が差分を表示し、ユーザーの承認を取る。"),
    parameters={
        "type": "object",
        "properties": {
            "file": {"type": "string", "enum": list(petit_home.PERSONA_FILES), "description": "変更するファイル"},
            "content": {"type": "string", "description": "変更後の全文"},
            "reason": {"type": "string", "description": "変更する理由（1文）"},
        },
        "required": ["file", "content", "reason"],
        "additionalProperties": False,
    },
    risk="confirm_write",
    preview=_preview,
)
def update_persona_file(file: str, content: str, reason: str) -> dict[str, Any]:
    if not content.strip():
        return {"updated": False, "error": "空の内容には置き換えられません。"}
    try:
        return petit_home.apply(file, content, reason)
    except petit_home.HomeError as exc:
        return {"updated": False, "error": str(exc)}
    except OSError:
        return {"updated": False, "error": "PETIT Home へ書き込めませんでした。"}
