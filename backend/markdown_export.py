"""Obsidian-friendly Markdown export for PETIT.

役割分担（Concept.md 準拠）:
- SQLite  : AI が検索する正本（構造化データ）
- Chroma  : 意味検索(RAG) の正本
- Markdown: 人が読む・育てる・他ツールへ持ち出す副本 ← このモジュール

設計方針:
- 追記専用。既存ログは上書き・要約・削除しない（progress ルールと同じ思想）。
- YAML フロントマター + ウィキリンク([[...]]) で Obsidian の Dataview / グラフを活かす。
- 書き込み失敗してもサーバーは落とさない（best-effort）。
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

from . import config

log = logging.getLogger(__name__)


def _today_str() -> str:
    return date.today().isoformat()


def _hm(ts_iso: str | None) -> str:
    """Render an ISO timestamp as HH:MM (best-effort)."""
    if not ts_iso:
        return datetime.now().strftime("%H:%M")
    try:
        return datetime.fromisoformat(ts_iso).strftime("%H:%M")
    except ValueError:
        return ts_iso[11:16] if len(ts_iso) >= 16 else ts_iso


def _daily_path(day: str) -> Path:
    return config.AI_DAILY_DIR / f"{day}.md"


def _ensure_daily_header(path: Path, day: str) -> None:
    """Create the daily note with frontmatter + headings if it doesn't exist yet."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "---\n"
        f"date: {day}\n"
        "type: daily\n"
        "tags: [petit, daily]\n"
        "---\n\n"
        f"# {day}\n\n"
        "## 会話ログ\n\n"
        "## まとめ\n\n"
    )
    path.write_text(header, encoding="utf-8")


def append_conversation_turn(
    user_text: str,
    assistant_text: str,
    used_tools: str | None,
    timestamp: str | None = None,
) -> bool:
    """Append one chat turn to today's Obsidian daily note (best-effort)."""
    try:
        day = _today_str()
        path = _daily_path(day)
        _ensure_daily_header(path, day)

        tool_note = f"  _(tools: {used_tools})_" if used_tools else ""
        block = (
            f"- **{_hm(timestamp)}**{tool_note}\n"
            f"    - 🧑 {user_text}\n"
            f"    - 🤖 {assistant_text}\n"
        )
        with path.open("a", encoding="utf-8") as f:
            f.write(block)
        return True
    except Exception as exc:  # noqa: BLE001 - md export must never crash the request
        log.debug("markdown append (turn) failed: %s", exc)
        return False


def append_summary(summary: str, facts: list[str] | None, kind: str = "interval") -> bool:
    """Append an interval/daily summary block under today's '## まとめ' note."""
    try:
        day = _today_str()
        path = _daily_path(day)
        _ensure_daily_header(path, day)

        lines = [f"\n### {_hm(None)} 自動まとめ（{kind}）\n", f"{summary}\n"]
        if facts:
            lines.append("\n**覚えておくこと:**\n")
            lines.extend(f"- {fact}\n" for fact in facts)
        with path.open("a", encoding="utf-8") as f:
            f.write("".join(lines))
        return True
    except Exception as exc:  # noqa: BLE001
        log.debug("markdown append (summary) failed: %s", exc)
        return False


def append_episode(episode: dict[str, Any]) -> bool:
    """Write one readable episode note; raw turn logs remain in the daily note."""
    try:
        day = str(episode["started_at"])[:10]
        stamp = str(episode["started_at"])[11:16].replace(":", "-")
        path = config.AI_DAILY_DIR / f"{day}-episode-{episode['episode_id']}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        def block(name: str, raw: str) -> str:
            import json
            values = json.loads(raw) if raw else []
            return "\n".join(f"- {value}" for value in values) or "- なし"
        path.write_text(
            f"---\ntype: petit_episode\nepisode_id: {episode['episode_id']}\nstarted_at: {episode['started_at']}\nended_at: {episode['ended_at']}\n---\n\n"
            f"# {episode['title']} - {day} {stamp}\n\n## 概要\n\n{episode['summary']}\n\n## 決定事項\n\n{block('decisions', episode['decisions'])}\n\n## 作業中\n\n{block('work', episode['work_in_progress'])}\n\n## 次にやること\n\n{block('next', episode['next_action'])}\n\n## 関連会話\n\n{episode['source_ids']}\n",
            encoding="utf-8",
        )
        return True
    except Exception as exc:  # noqa: BLE001
        log.debug("markdown append (episode) failed: %s", exc)
        return False


def append_memory(content: str, mem_type: str = "note") -> bool:
    """Append a durable memory item to AI_Memory/<type>.md (Obsidian-linkable).

    日次ノートからは [[profile]] のように辿れる。人が後から育てる用。
    """
    try:
        config.AI_MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        safe_type = "".join(c for c in mem_type if c.isalnum() or c in ("-", "_")) or "note"
        path = config.AI_MEMORY_DIR / f"{safe_type}.md"
        if not path.exists():
            path.write_text(
                "---\n"
                f"type: memory/{safe_type}\n"
                "tags: [petit, memory]\n"
                "---\n\n"
                f"# {safe_type}\n\n",
                encoding="utf-8",
            )
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        with path.open("a", encoding="utf-8") as f:
            f.write(f"- ({stamp}) {content}  [[{_today_str()}]]\n")
        return True
    except Exception as exc:  # noqa: BLE001
        log.debug("markdown append (memory) failed: %s", exc)
        return False


def status() -> dict[str, Any]:
    """Lightweight health info for the /api/health endpoint."""
    daily = config.AI_DAILY_DIR
    return {
        "daily_dir": str(daily),
        "memory_dir": str(config.AI_MEMORY_DIR),
        "daily_notes": len(list(daily.glob("*.md"))) if daily.exists() else 0,
    }
