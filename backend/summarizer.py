"""Asynchronous episode finalization for PETIT's durable conversation memory."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from . import chroma_client, config, db, markdown_export
from .lmstudio_client import LMStudioError, chat_completion

log = logging.getLogger(__name__)

_SYSTEM = """あなたはPETITの会話エピソード整理機能です。会話に明記されたことだけを抽出し、推測を加えないでください。
必ず次のJSONだけを返してください:
{"title":"","summary":"","decisions":[],"facts":[],"work_in_progress":[],"next_action":[]}
雑談だけなら summary は空文字にしてください。長期的に再利用できない一時的な発言は facts に入れません。"""


def _transcript(rows: list[dict[str, Any]]) -> str:
    return "\n\n".join(f"[{r['timestamp']}]\nユーザー: {r['user_text']}\nPETIT: {r['assistant_text']}" for r in rows)


def _json(text: str) -> dict[str, Any] | None:
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text or "", re.S)
    candidate = match.group(1) if match else (text or "").strip()
    if not candidate.startswith("{"):
        start, end = candidate.find("{"), candidate.rfind("}")
        candidate = candidate[start:end + 1] if start >= 0 and end > start else ""
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _items(value: Any) -> list[str]:
    return [str(item).strip() for item in value] if isinstance(value, list) else []


def _eligible(rows: list[dict[str, Any]], force: bool) -> bool:
    if force or len(rows) >= config.EPISODE_MAX_TURNS:
        return True
    try:
        latest = datetime.fromisoformat(rows[-1]["timestamp"])
        return (datetime.now(timezone.utc) - latest).total_seconds() >= config.EPISODE_IDLE_MINUTES * 60
    except (ValueError, TypeError):
        return False


def _episode_text(parsed: dict[str, Any]) -> str:
    values = [str(parsed.get("title", "")).strip(), str(parsed.get("summary", "")).strip()]
    for key in ("decisions", "facts", "work_in_progress", "next_action"):
        values.extend(_items(parsed.get(key)))
    return "\n".join(value for value in values if value)


def summarize_pending(kind: str = "interval", min_conversations: int | None = None, force: bool = False) -> dict[str, Any]:
    """Finalize eligible unassigned turns. Failure leaves them untouched for retry."""
    threshold = config.SUMMARY_MIN_CONVERSATIONS if min_conversations is None else min_conversations
    groups = [rows for rows in db.pending_episode_groups() if len(rows) >= threshold and _eligible(rows, force)]
    if not groups:
        return {"summarized": False, "reason": "no_eligible_episode", "pending": sum(len(x) for x in db.pending_episode_groups())}
    rows = groups[0]  # one bounded LLM job per scheduler tick
    try:
        result = chat_completion([{"role": "system", "content": _SYSTEM}, {"role": "user", "content": _transcript(rows)}], tools=None, temperature=0.2, model=config.AGENT_MODEL)
    except LMStudioError as exc:
        return {"summarized": False, "reason": "lm_unavailable", "error": str(exc)}
    parsed = _json((result.get("content") or "").strip())
    if parsed is None:
        return {"summarized": False, "reason": "invalid_json"}
    summary = str(parsed.get("summary") or "").strip()
    title = str(parsed.get("title") or "").strip()
    if not summary or not title:
        return {"summarized": False, "reason": "empty_episode"}
    ids = [int(row["id"]) for row in rows]
    text = _episode_text(parsed)
    data = {
        "started_at": rows[0]["timestamp"], "ended_at": rows[-1]["timestamp"], "title": title, "summary": summary,
        "decisions": json.dumps(_items(parsed.get("decisions")), ensure_ascii=False), "facts": json.dumps(_items(parsed.get("facts")), ensure_ascii=False),
        "work_in_progress": json.dumps(_items(parsed.get("work_in_progress")), ensure_ascii=False), "next_action": json.dumps(_items(parsed.get("next_action")), ensure_ascii=False),
        "source_ids": json.dumps(ids), "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
    episode_id = db.save_episode(data)
    markdown_export.append_episode({**data, "episode_id": episode_id})
    saved = 0
    # Automatic promotion is intentionally narrow. Explicit save_memory remains separate.
    for item, mem_type in [(x, "decision") for x in _items(parsed.get("decisions"))] + [(x, "fact") for x in _items(parsed.get("facts"))] + [(x, "project") for x in _items(parsed.get("work_in_progress"))]:
        if len(item) < 8:
            continue
        memory_id, created = db.save_memory_item(item, mem_type, "auto_episode")
        if created:
            saved += 1
    chroma_client.sync_structured_data(db.all_memory(), db.all_episodes())
    return {"summarized": True, "episode_id": episode_id, "conv_count": len(rows), "kind": kind, "memories_saved": saved}
