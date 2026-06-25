"""Always-on memory recall — inject what PETIT "remembers" into every turn.

人間っぽさの正体のひとつ「自分を覚えている感」を出すための層。
毎ターン、関連する記憶・最近の要約を取り出してプロンプトに自然に混ぜる。

ブレンド方針（人間の想起に寄せる）:
- 直近の要約 = 「さっきまで何をしていたか」(recency)
- 意味検索でヒットした記憶 = 「その話題に関係する事実」(relevance)

LM Studio が落ちていて embedding が使えない場合は、最近の行をそのまま使う
（検索精度は落ちるが「忘れる」よりマシ）。失敗してもサーバーは落とさない。
"""
from __future__ import annotations

import logging
from typing import Any

from . import chroma_client, db

log = logging.getLogger(__name__)

_MAX_LEN = 200  # 1項目あたりの最大文字数（トークン節約）


def _clip(text: str) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= _MAX_LEN else text[:_MAX_LEN] + "…"


def build_recall_block(user_message: str, max_memories: int = 5, max_summaries: int = 2) -> str:
    """Return a compact context block to inject as a system message, or "".

    Always best-effort: any error yields "" so the chat turn proceeds normally.
    """
    try:
        memories = _relevant_memories(user_message, max_memories)
        summaries = _recent_summaries_text(max_summaries)
    except Exception as exc:  # noqa: BLE001 - recall must never break a chat turn
        log.debug("recall failed: %s", exc)
        return ""

    if not memories and not summaries:
        return ""

    lines = [
        "【PETITが覚えていること】",
        "（あなたが自然に会話へ織り込んでよい背景知識。"
        "聞かれてもいないのに一覧で読み上げない。関係するときだけ自然に触れる。）",
    ]
    if summaries:
        lines.append("- 最近の流れ:")
        lines.extend(f"    - {s}" for s in summaries)
    if memories:
        lines.append("- 関連して覚えていること:")
        lines.extend(f"    - {m}" for m in memories)
    return "\n".join(lines)


def _relevant_memories(query: str, limit: int) -> list[str]:
    """Semantically relevant memories; fall back to recent rows if embeddings are down."""
    results = chroma_client.query("petit_memory", query, n_results=limit)
    if results:  # non-empty list -> embeddings worked and matched
        return [_clip(r["document"]) for r in results]
    if results is None:  # embeddings unavailable -> recent rows fallback
        rows = db.all_memory()[-limit:]
        return [_clip(r["content"]) for r in rows]
    return []  # [] -> collection empty / no match


def _recent_summaries_text(limit: int) -> list[str]:
    rows = db.recent_summaries(limit=limit)
    return [_clip(r["summary"]) for r in rows if r.get("summary")]
