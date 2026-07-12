"""Confirmed, path-safe edits for Markdown notes in configured BRAIN vaults."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import config, vault_indexer
from .registry import tool


@tool(
    name="search_brain_notes",
    description=(
        "設定済みBRAIN/Obsidian vaultのMarkdownを、ファイル名・見出し・本文から高速に絞り込み検索する。"
        "BRAINを明示した質問や編集対象ノートの特定で使う。Embeddingは実行しない。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "検索語または自然な質問"},
            "limit": {"type": "integer", "description": "最大件数", "default": 5},
        },
        "required": ["query"],
    },
)
def search_brain_notes(query: str, limit: int = 5) -> dict[str, Any]:
    notes = vault_indexer.keyword_search(query, limit=max(1, min(limit, 10)))
    return {"query": query, "count": len(notes), "vault_notes": notes, "search_type": "bounded_keyword"}


@tool(
    name="edit_brain_note",
    description=(
        "設定済みObsidian/BRAIN vault内の既存Markdownノートへ追記または完全一致置換を行う。"
        "search_memoryのvault_notesにあるrelative_pathで対象を特定してから使う。"
        "_private、Vault外、Markdown以外は編集できない。実行前に必ず確認される。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "relative_path": {"type": "string", "description": "Vaultルートからの相対Markdownパス"},
            "mode": {"type": "string", "enum": ["append", "replace"], "description": "追記または置換"},
            "content": {"type": "string", "description": "追記する本文、または置換後の本文"},
            "old_text": {"type": "string", "description": "replace時に1箇所だけ完全一致する置換前本文"},
            "vault_index": {"type": "integer", "description": "複数Vault時の番号。既定0", "default": 0},
        },
        "required": ["relative_path", "mode", "content"],
    },
    requires_confirmation=True,
)
def edit_brain_note(
    relative_path: str,
    mode: str,
    content: str,
    old_text: str | None = None,
    vault_index: int = 0,
) -> dict[str, Any]:
    root, target = _safe_target(relative_path, vault_index)
    if not target.exists() or not target.is_file():
        return {"updated": False, "error": "対象Markdownノートが見つかりません。", "relative_path": relative_path}

    current = target.read_text(encoding="utf-8-sig")
    if mode == "append":
        addition = content.strip()
        if not addition:
            return {"updated": False, "error": "追記内容が空です。", "relative_path": relative_path}
        updated = current.rstrip() + "\n\n" + addition + "\n"
    elif mode == "replace":
        if not old_text:
            return {"updated": False, "error": "replaceにはold_textが必要です。", "relative_path": relative_path}
        matches = current.count(old_text)
        if matches != 1:
            return {
                "updated": False,
                "error": f"old_textの一致数が{matches}件です。安全のため1件のときだけ置換します。",
                "relative_path": relative_path,
            }
        updated = current.replace(old_text, content, 1)
    else:
        return {"updated": False, "error": "modeはappendまたはreplaceです。", "relative_path": relative_path}

    temp = target.with_name(target.name + ".petit.tmp")
    temp.write_text(updated, encoding="utf-8")
    temp.replace(target)
    try:
        index_result = vault_indexer._index_file(root, target)
    except Exception as exc:  # noqa: BLE001 - note edit already succeeded
        index_result = {"indexed": 0, "error": type(exc).__name__}
    return {
        "updated": True,
        "relative_path": str(target.relative_to(root)),
        "mode": mode,
        "indexed": index_result,
    }


def _safe_target(relative_path: str, vault_index: int) -> tuple[Path, Path]:
    if not config.OBSIDIAN_VAULT_DIRS:
        raise ValueError("PETIT_OBSIDIAN_VAULT_DIRSが設定されていません。")
    if vault_index < 0 or vault_index >= len(config.OBSIDIAN_VAULT_DIRS):
        raise ValueError("vault_indexが設定済みVaultの範囲外です。")
    raw = Path(relative_path)
    if raw.is_absolute() or ".." in raw.parts or raw.suffix.casefold() != ".md":
        raise ValueError("Vault内の相対Markdownパスだけを指定できます。")
    if any(part.casefold() in {name.casefold() for name in vault_indexer.EXCLUDED_DIR_NAMES} for part in raw.parts):
        raise ValueError("除外フォルダ内のノートは編集できません。")

    root = config.OBSIDIAN_VAULT_DIRS[vault_index].resolve()
    target = (root / raw).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("Vault外のパスは編集できません。") from exc
    return root, target
