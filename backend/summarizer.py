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
{"title":"","summary":"","decisions":[],"facts":[],"work_in_progress":[],"next_action":[],"durable_knowledge":[]}
雑談だけなら summary は空文字にしてください。長期的に再利用できない一時的な発言は facts に入れません。

durable_knowledge には、数か月後の別の会話でもそのまま正しい、ユーザー本人についての知識だけを入れます。
各要素は {"kind":"preference|profile|decision|fact","text":"..."} です。text は主語と対象が分かる、それだけで読める一文にします。
入れるもの: ユーザー本人が述べた好み・習慣、本人や身近な人・物・プロジェクトの名前と関係、PETITへの継続的な頼み方、長く続く方針。
入れないもの: 時刻や日付そのもの、その日の予定、タスクや予定の件数・一覧、同期や接続の状態、PETITが実行・確認した操作、作業の途中経過、PETIT自身の機能や不具合、PETITの発言だけに出てくる内容。
迷ったら入れません。該当がなければ空配列にします。"""

# Episode facts, decisions and work in progress describe that conversation and stay in the
# episode. Only knowledge the model marks as durable becomes a standing memory.
DURABLE_SOURCE = "auto_knowledge"
DURABLE_KINDS = {"preference", "profile", "decision", "fact"}
MAX_DURABLE_PER_EPISODE = 5
# The reply is one JSON object; the default light budget cut longer sessions off mid-object.
SUMMARY_MAX_TOKENS = 1500


def _durable(value: Any) -> list[tuple[str, str]]:
    found = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue  # an unlabelled string is the old free-form shape; do not promote it
        text, kind = str(item.get("text") or "").strip(), str(item.get("kind") or "").strip().lower()
        if len(text) >= 8 and len(text) <= 300 and kind in DURABLE_KINDS:
            found.append((text, kind))
    return found[:MAX_DURABLE_PER_EPISODE]


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


def summarize_pending(kind: str = "interval", min_conversations: int | None = None, force: bool = False,
                      tried: set[int] | None = None) -> dict[str, Any]:
    """Finalize one eligible session's unassigned turns.

    A model outage leaves the turns untouched. Unreadable output is retried on later runs, a few
    times; a session with nothing to keep is set aside at once. Either way later sessions go on.
    ``tried`` collects the sessions already attempted in the caller's run.
    """
    threshold = config.SUMMARY_MIN_CONVERSATIONS if min_conversations is None else min_conversations
    tried = set() if tried is None else tried
    groups = [rows for rows in db.pending_episode_groups()
              if len(rows) >= threshold and _eligible(rows, force) and int(rows[0]["id"]) not in tried]
    if not groups:
        return {"summarized": False, "reason": "no_eligible_episode", "pending": sum(len(x) for x in db.pending_episode_groups())}
    # One bounded LLM job: a long session is summarized a stretch at a time, oldest first.
    rows = groups[0][:max(1, config.EPISODE_MAX_TURNS)]
    ids = [int(row["id"]) for row in rows]
    try:
        result = chat_completion(
            [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": _transcript(rows)}],
            tools=None,
            temperature=0.2,
            model=config.AGENT_MODEL,
            max_tokens=SUMMARY_MAX_TOKENS,
            route="agent",
        )
    except LMStudioError as exc:
        return {"summarized": False, "reason": "lm_unavailable", "error": str(exc)}
    parsed = _json((result.get("content") or "").strip())
    if parsed is None:
        tried.add(ids[0])
        return {"summarized": False, "reason": "invalid_json", "gave_up": db.skip_summary(ids, "invalid_json")}
    summary = str(parsed.get("summary") or "").strip()
    title = str(parsed.get("title") or "").strip()
    if not summary or not title:
        db.skip_summary(ids, "empty_episode", final=True)
        return {"summarized": False, "reason": "empty_episode", "gave_up": True}
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
    for item, mem_type in _durable(parsed.get("durable_knowledge")):
        memory_id, created = db.save_memory_item(item, mem_type, DURABLE_SOURCE)
        if created:
            saved += 1
    chroma_client.sync_structured_data(db.all_memory(), db.all_episodes())
    return {"summarized": True, "episode_id": episode_id, "conv_count": len(rows), "kind": kind, "memories_saved": saved}


def summarize_backlog(kind: str = "interval", limit: int | None = None) -> dict[str, Any]:
    """One scheduler run: work through several waiting sessions, stopping when the model is unavailable."""
    limit = config.SUMMARY_MAX_PER_TICK if limit is None else limit
    episodes = skipped = saved = 0
    tried: set[int] = set()
    last: dict[str, Any] = {"reason": "no_eligible_episode"}
    for _ in range(max(1, limit)):
        last = summarize_pending(kind=kind, tried=tried)
        if last.get("summarized"):
            episodes += 1
            saved += int(last.get("memories_saved") or 0)
        elif last.get("reason") in {"empty_episode", "invalid_json"}:
            skipped += 1
        else:
            break
    result = {"summarized": bool(episodes), "episodes": episodes, "skipped": skipped, "memories_saved": saved,
              "pending": sum(len(rows) for rows in db.pending_episode_groups())}
    if not episodes:
        result["reason"] = last.get("reason")
    if last.get("error"):
        result["error"] = last["error"]
    return result
