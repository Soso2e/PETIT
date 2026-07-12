"""Periodic conversation summarizer — the heart of PETIT's memory accumulation.

何をするか:
1. まだ要約していない会話ターンを集める（前回の続きから）
2. LLM に「要約 + 覚えておくべき事実/作業中の内容/タスク」を JSON で出させる
3. 結果を SQLite(summaries) + Chroma(petit_summaries) + Markdown に蓄積
4. 抽出した durable な事実を長期記憶(memory)へ自動保存（会話からデータが育つ）

LM Studio が落ちていても例外で止めず、{"summarized": False, ...} を返す。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from . import chroma_client, config, db, markdown_export
from .lmstudio_client import LMStudioError, chat_completion

log = logging.getLogger(__name__)

_SUMMARY_SYSTEM = """あなたはユーザー専用アシスタント「PETIT」の記憶整理エンジンです。
渡された会話ログを読み、後でユーザーを助けるために必要な情報だけを抽出します。

必ず次の JSON だけを出力してください（前後に説明文を付けない）:
{
  "summary": "この期間に何があったかの簡潔な要約（日本語・2〜4文）",
  "facts": ["長期的に覚えておくべき事実・好み・決定事項（なければ空配列）"],
  "work_in_progress": ["今やっている/中断中の作業・タスク（なければ空配列）"]
}

ルール:
- 雑談だけで覚える価値がなければ facts と work_in_progress は空配列にする。
- 推測で事実を作らない。会話に書かれたことだけを抽出する。
- facts と work_in_progress の各要素は、それ単体で読んで分かる短い文にする。"""


def _build_transcript(convs: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for c in convs:
        lines.append(f"[{c.get('timestamp', '')}]")
        lines.append(f"ユーザー: {c.get('user_text', '')}")
        lines.append(f"PETIT: {c.get('assistant_text', '')}")
        lines.append("")
    return "\n".join(lines)


def _extract_json(text: str) -> dict[str, Any]:
    """Lenient JSON extraction — models often wrap JSON in prose or code fences."""
    if not text:
        return {}
    # Strip code fences if present
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        start = text.find("{")
        end = text.rfind("}")
        candidate = text[start : end + 1] if start != -1 and end > start else text
    try:
        data = json.loads(candidate)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def summarize_pending(kind: str = "interval", min_conversations: int | None = None) -> dict[str, Any]:
    """Summarize all not-yet-summarized conversation turns.

    Returns a small status dict; never raises for an unreachable backend.
    """
    threshold = config.SUMMARY_MIN_CONVERSATIONS if min_conversations is None else min_conversations
    last_id = db.last_summarized_conv_id()
    convs = db.conversations_after(last_id)

    if len(convs) < threshold:
        return {"summarized": False, "reason": "no_new_conversations", "pending": len(convs)}

    transcript = _build_transcript(convs)
    messages = [
        {"role": "system", "content": _SUMMARY_SYSTEM},
        {"role": "user", "content": f"次の会話ログをまとめてください。\n\n{transcript}"},
    ]

    try:
        # temperature low for stable JSON
        message = chat_completion(messages, tools=None, temperature=0.2, model=config.AGENT_MODEL)
    except LMStudioError as exc:
        log.info("Summarization skipped (LM Studio unavailable): %s", exc)
        return {"summarized": False, "reason": "lm_unavailable", "error": str(exc)}

    raw = (message.get("content") or "").strip()
    if not raw:
        return {"summarized": False, "reason": "empty_model_response"}
    parsed = _extract_json(raw)

    summary_text = str(parsed.get("summary", "")).strip() or raw[:500]
    if not summary_text:
        return {"summarized": False, "reason": "empty_summary"}
    facts = _as_str_list(parsed.get("facts"))
    wip = _as_str_list(parsed.get("work_in_progress"))
    all_facts = facts + [f"作業中: {w}" for w in wip]

    period_start = convs[0].get("timestamp")
    period_end = convs[-1].get("timestamp")
    last_conv_id = int(convs[-1]["id"])

    # 1) SQLite (正本)
    summary_id = db.save_summary(
        summary=summary_text,
        facts=json.dumps(all_facts, ensure_ascii=False) if all_facts else None,
        kind=kind,
        period_start=period_start,
        period_end=period_end,
        last_conv_id=last_conv_id,
        conv_count=len(convs),
    )

    # 2) Chroma (意味検索用)
    chroma_client.add(
        "petit_summaries",
        doc_id=f"sum_{summary_id}",
        text=summary_text + ("\n" + "\n".join(all_facts) if all_facts else ""),
        metadata={"kind": kind, "created_at": db.now_iso(), "conv_count": len(convs)},
    )

    # 3) 抽出した事実を長期記憶へ自動蓄積（会話からデータが育つ）
    saved_memories = 0
    for fact in facts:
        _save_durable_memory(fact, mem_type="fact")
        saved_memories += 1
    for w in wip:
        _save_durable_memory(w, mem_type="project")
        saved_memories += 1

    # 4) Markdown (人が読む副本)
    markdown_export.append_summary(summary_text, all_facts, kind=kind)

    log.info(
        "Summarized %d conversations -> summary #%d (%d facts/wip, %d memories)",
        len(convs), summary_id, len(all_facts), saved_memories,
    )
    return {
        "summarized": True,
        "summary_id": summary_id,
        "conv_count": len(convs),
        "kind": kind,
        "facts": all_facts,
        "memories_saved": saved_memories,
    }


def _save_durable_memory(content: str, mem_type: str) -> None:
    """Persist one extracted memory to SQLite + Chroma + Markdown (best-effort)."""
    now = db.now_iso()
    with db.get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO memory (created_at, type, content) VALUES (?, ?, ?)",
            (now, mem_type, content),
        )
        mem_id = int(cur.lastrowid)
    chroma_client.add(
        "petit_memory",
        doc_id=f"mem_{mem_id}",
        text=content,
        metadata={"type": mem_type, "created_at": now, "source": "auto_summary"},
    )
    markdown_export.append_memory(content, mem_type)
