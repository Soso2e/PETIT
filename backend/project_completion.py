"""Project-aware completion confirmation for PETIT.

A vague "終わった" starts a short-lived draft. A later scope answer becomes a
preview-only pending action; only the existing approval endpoint commits the
checkpoint and event.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from . import db, project_continuity

log = logging.getLogger(__name__)

_DRAFT_TTL_MINUTES = 30
_COMPLETION_START = re.compile(
    r"(?:終わった|できた|ここまで(?:にする|で終わり)?|一旦終わり|今日は終わり|作業終わり|完了した)",
    re.IGNORECASE,
)
_TASK_WRITE_PATTERN = re.compile(r"(?:タスク.*(?:完了|終わ)|完了にして|ステータス.*完了)", re.IGNORECASE)
_NEGATIONS = ("まだ", "未確認", "未実施", "してない", "していない", "できてない", "できていない", "残って")
_PIPELINE_ITEMS = ("実装", "自動テスト", "実画面確認", "デプロイ", "本番確認")
_STAGE_LABELS = {
    "implemented": "実装済み",
    "automated_tests_verified": "自動テスト確認済み",
    "ui_verified": "実画面確認済み",
    "deployed": "デプロイ済み",
    "production_verified": "本番確認済み",
    "paused": "一旦区切り",
    "blocked": "ブロック中",
    "completed": "完全完了",
}
_EVENT_TYPES = {
    "implemented": "implementation_completed",
    "automated_tests_verified": "tests_verified",
    "ui_verified": "ui_verified",
    "deployed": "deployed",
    "production_verified": "production_verified",
    "paused": "paused",
    "blocked": "blocked",
    "completed": "completed",
}

_COMPLETION_SCHEMA = """
CREATE TABLE IF NOT EXISTS project_completion_drafts (
    user_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    initial_message TEXT NOT NULL,
    summary_hint TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    provider TEXT NOT NULL DEFAULT 'petit',
    event_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    source_conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    idempotency_key TEXT NOT NULL UNIQUE,
    occurred_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_project_events_project_time
ON project_events(project_id, occurred_at);
"""


def ensure_completion_schema() -> None:
    project_continuity.ensure_project_schema()
    with db.get_connection() as conn:
        conn.executescript(_COMPLETION_SCHEMA)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _is_expired(expires_at: str) -> bool:
    try:
        return datetime.fromisoformat(expires_at) <= _utc_now()
    except ValueError:
        return True


def get_completion_draft(user_id: str) -> dict[str, Any] | None:
    ensure_completion_schema()
    with db.get_connection() as conn:
        row = conn.execute("SELECT * FROM project_completion_drafts WHERE user_id=?", (user_id,)).fetchone()
        if row and _is_expired(str(row["expires_at"])):
            conn.execute("DELETE FROM project_completion_drafts WHERE user_id=?", (user_id,))
            return None
    return dict(row) if row else None


def _save_draft(user_id: str, project_id: str, initial_message: str, summary_hint: str) -> dict[str, Any]:
    ensure_completion_schema()
    now = _utc_now()
    expires = now + timedelta(minutes=_DRAFT_TTL_MINUTES)
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO project_completion_drafts (user_id, project_id, initial_message, summary_hint, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET project_id=excluded.project_id, initial_message=excluded.initial_message, "
            "summary_hint=excluded.summary_hint, created_at=excluded.created_at, expires_at=excluded.expires_at",
            (user_id, project_id, initial_message, summary_hint, now.isoformat(), expires.isoformat()),
        )
    return get_completion_draft(user_id) or {}


def _clear_draft(user_id: str) -> None:
    ensure_completion_schema()
    with db.get_connection() as conn:
        conn.execute("DELETE FROM project_completion_drafts WHERE user_id=?", (user_id,))


def _is_completion_start(message: str) -> bool:
    text = message.strip()
    if not text or _TASK_WRITE_PATTERN.search(text):
        return False
    if text.endswith(("?", "？")):
        return False
    return bool(_COMPLETION_START.search(text))


def _summary_hint(message: str, project_name: str, history: list[dict[str, str]] | None) -> str:
    stripped = _COMPLETION_START.sub("", message)
    stripped = re.sub(r"(?:一旦|とりあえず|やっと|これで|は|が|を|も)+", " ", stripped).strip(" 、。！!")
    if len(stripped) >= 3:
        return stripped[:160]
    for item in reversed(history or []):
        if item.get("role") != "user":
            continue
        content = " ".join(str(item.get("content") or "").split())
        if not content or _is_completion_start(content):
            continue
        if len(content) >= 4:
            return content[:160]
    return f"{project_name}の作業"


def _term_negative(text: str, terms: tuple[str, ...]) -> bool:
    for term in terms:
        for match in re.finditer(re.escape(term), text, re.IGNORECASE):
            window = text[max(0, match.start() - 8): min(len(text), match.end() + 10)]
            if any(negative in window for negative in _NEGATIONS):
                return True
    return False


def _term_positive(text: str, terms: tuple[str, ...]) -> bool:
    return any(term.casefold() in text.casefold() for term in terms) and not _term_negative(text, terms)


def _extract_next_action(text: str) -> str | None:
    match = re.search(r"(?:次は|次に|次の作業は)\s*(.+?)(?:[。.!！]|$)", text)
    return match.group(1).strip()[:200] if match and match.group(1).strip() else None


def _merge_unique(base: list[str], additions: list[str]) -> list[str]:
    result: list[str] = []
    for item in [*base, *additions]:
        value = str(item).strip()
        if value and value not in result:
            result.append(value)
    return result


def _remove_verified(items: list[str], verified: set[str]) -> list[str]:
    return [item for item in items if item not in verified]


def _parse_scope(
    text: str,
    *,
    checkpoint: dict[str, Any] | None,
) -> dict[str, Any] | None:
    compact = " ".join(text.strip().split())
    if not compact:
        return None

    explicit_completed = bool(re.search(r"(?:完全に|全部|すべて|もう残り(?:は)?ない).{0,6}(?:完了|終わ)", compact))
    paused = bool(re.search(r"(?:今日はここまで|一旦(?:ここまで|終わり)|保留|中断|今日は終わり)", compact))
    blocked = bool(re.search(r"(?:ブロッカー|詰まった|詰まって|進めない|進まない|エラーで止ま)", compact))

    production_negative = _term_negative(compact, ("本番確認", "本番で確認", "公開確認"))
    deploy_negative = _term_negative(compact, ("デプロイ", "公開", "反映"))
    ui_negative = _term_negative(compact, ("ブラウザ", "実画面", "画面確認", "実機"))
    test_negative = _term_negative(compact, ("テスト", "unittest", "build", "ビルド"))

    production = _term_positive(compact, ("本番確認", "本番で確認", "公開確認"))
    deployed = _term_positive(compact, ("デプロイ", "公開した", "反映した"))
    ui_verified = _term_positive(compact, ("ブラウザ確認", "実画面", "画面確認", "実機確認"))
    tested = _term_positive(compact, ("テスト通った", "テストも通った", "テスト済み", "unittest", "build成功", "ビルド成功"))
    implemented = _term_positive(compact, ("実装", "作った", "組んだ", "コード", "修正できた"))

    if explicit_completed:
        stage = "completed"
    elif blocked:
        stage = "blocked"
    elif paused:
        stage = "paused"
    elif production:
        stage = "production_verified"
    elif deployed:
        stage = "deployed"
    elif ui_verified:
        stage = "ui_verified"
    elif tested:
        stage = "automated_tests_verified"
    elif implemented:
        stage = "implemented"
    else:
        return None

    old_evidence = list((checkpoint or {}).get("completed_evidence") or [])
    old_unverified = list((checkpoint or {}).get("unverified_items") or [])
    old_blockers = list((checkpoint or {}).get("blockers") or [])

    evidence: list[str] = []
    verified_items: set[str] = set()
    if implemented or stage in {"automated_tests_verified", "ui_verified", "deployed", "production_verified", "completed"}:
        evidence.append("実装済み（ユーザー確認）")
        verified_items.add("実装")
    if tested or stage in {"ui_verified", "deployed", "production_verified", "completed"}:
        evidence.append("自動テスト確認済み（ユーザー確認）")
        verified_items.add("自動テスト")
    if ui_verified or stage in {"deployed", "production_verified", "completed"}:
        evidence.append("実画面確認済み（ユーザー確認）")
        verified_items.add("実画面確認")
    if deployed or stage in {"production_verified", "completed"}:
        evidence.append("デプロイ済み（ユーザー確認）")
        verified_items.add("デプロイ")
    if production or stage == "completed":
        evidence.append("本番確認済み（ユーザー確認）")
        verified_items.add("本番確認")

    unverified = _remove_verified(old_unverified, verified_items)
    explicit_unverified: list[str] = []
    if test_negative:
        explicit_unverified.append("自動テスト")
    if ui_negative:
        explicit_unverified.append("実画面確認")
    if deploy_negative:
        explicit_unverified.append("デプロイ")
    if production_negative:
        explicit_unverified.append("本番確認")

    defaults: list[str] = []
    if stage == "implemented":
        defaults = ["自動テスト", "実画面確認", "デプロイ", "本番確認"]
    elif stage == "automated_tests_verified":
        defaults = ["実画面確認", "デプロイ", "本番確認"]
    elif stage == "ui_verified":
        defaults = ["デプロイ", "本番確認"]
    elif stage == "deployed":
        defaults = ["本番確認"]
    elif stage in {"production_verified", "completed"}:
        defaults = []
    unverified = _merge_unique(unverified, [*defaults, *explicit_unverified])
    if stage == "completed":
        unverified = []

    blockers = old_blockers
    if blocked:
        blockers = _merge_unique(old_blockers, [f"ユーザー報告: {compact[:200]}"])
    elif stage == "completed":
        blockers = []

    return {
        "stage": stage,
        "stage_label": _STAGE_LABELS[stage],
        "event_type": _EVENT_TYPES[stage],
        "completed_evidence": _merge_unique(old_evidence, evidence),
        "unverified_items": unverified,
        "blockers": blockers,
        "next_action": _extract_next_action(compact) or (checkpoint or {}).get("next_action"),
    }


def _completion_arguments(
    *,
    user_id: str,
    project: dict[str, Any],
    summary_hint: str,
    source_text: str,
    draft_created_at: str,
    parsed: dict[str, Any],
) -> dict[str, Any]:
    summary = f"{summary_hint}：{parsed['stage_label']}"
    digest_source = f"{user_id}|{project['project_id']}|{draft_created_at}|{' '.join(source_text.casefold().split())}"
    idempotency_key = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()
    return {
        "user_id": user_id,
        "project_id": project["project_id"],
        "stage": parsed["stage"],
        "last_summary": summary,
        "next_action": parsed.get("next_action"),
        "blockers": parsed["blockers"],
        "completed_evidence": parsed["completed_evidence"],
        "unverified_items": parsed["unverified_items"],
        "event_type": parsed["event_type"],
        "event_summary": summary,
        "source_user_text": source_text,
        "idempotency_key": idempotency_key,
    }


def _preview_reply(project_name: str, args: dict[str, Any]) -> str:
    lines = [f"お疲れさま。「{project_name}」はこう記録するよ。", f"- 到達: {_STAGE_LABELS[args['stage']]}", f"- まとめ: {args['last_summary']}"]
    if args.get("completed_evidence"):
        lines.append(f"- 確認済み: {'、'.join(args['completed_evidence'])}")
    if args.get("unverified_items"):
        lines.append(f"- 未確認: {'、'.join(args['unverified_items'])}")
    if args.get("blockers"):
        lines.append(f"- ブロッカー: {'、'.join(args['blockers'])}")
    if args.get("next_action"):
        lines.append(f"- 次: {args['next_action']}")
    lines.append("この内容で保存する？")
    return "\n".join(lines)


def _pending_preview(
    *,
    user_id: str,
    project: dict[str, Any],
    summary_hint: str,
    source_text: str,
    draft_created_at: str,
    checkpoint: dict[str, Any] | None,
) -> dict[str, Any] | None:
    parsed = _parse_scope(source_text, checkpoint=checkpoint)
    if not parsed:
        return None
    args = _completion_arguments(
        user_id=user_id,
        project=project,
        summary_hint=summary_hint,
        source_text=source_text,
        draft_created_at=draft_created_at,
        parsed=parsed,
    )
    return {
        "reply": _preview_reply(str(project["name"]), args),
        "used_tools": [],
        "pending_actions": [{"name": "save_project_completion", "arguments": args}],
        "persist": True,
        "model_route": {"kind": "project_completion_preview", "model": None, "project_id": project["project_id"], "stage": parsed["stage"]},
    }


def try_handle_completion_turn(
    user_message: str,
    *,
    user_id: str,
    recent_history: list[dict[str, str]] | None = None,
) -> dict[str, Any] | None:
    """Handle a completion start or its pending scope answer without an LLM."""
    try:
        draft = get_completion_draft(user_id)
        if draft:
            project = project_continuity.get_active_project(user_id)
            if not project or project["project_id"] != draft["project_id"]:
                stored = project_continuity.get_project(str(draft["project_id"]))
                if not stored:
                    _clear_draft(user_id)
                    return None
                project = {"project_id": stored["id"], "name": stored["name"]}
            checkpoint = project_continuity.get_project_checkpoint(user_id, str(draft["project_id"]))
            preview = _pending_preview(
                user_id=user_id,
                project=project,
                summary_hint=str(draft.get("summary_hint") or f"{project['name']}の作業"),
                source_text=user_message,
                draft_created_at=str(draft["created_at"]),
                checkpoint=checkpoint,
            )
            if preview:
                return preview
            return {
                "reply": "どこまで終わったか、もう少しだけ教えて。実装まで、テストまで、実画面確認まで、デプロイまでのどれに近い？",
                "used_tools": [],
                "persist": True,
                "model_route": {"kind": "project_completion_clarification", "model": None, "project_id": draft["project_id"]},
            }

        if not _is_completion_start(user_message):
            return None
        active = project_continuity.get_active_project(user_id)
        if not active:
            return {
                "reply": "お疲れさま。どのプロジェクトの作業が終わったか、名前を教えて。",
                "used_tools": [],
                "persist": True,
                "model_route": {"kind": "project_completion_missing_project", "model": None},
            }
        summary_hint = _summary_hint(user_message, str(active["name"]), recent_history)
        checkpoint = project_continuity.get_project_checkpoint(user_id, str(active["project_id"]))
        direct = _pending_preview(
            user_id=user_id,
            project=active,
            summary_hint=summary_hint,
            source_text=user_message,
            draft_created_at=db.now_iso(),
            checkpoint=checkpoint,
        )
        if direct:
            return direct
        draft = _save_draft(user_id, str(active["project_id"]), user_message, summary_hint)
        return {
            "reply": f"お疲れさま。「{active['name']}」は一旦できたんだね。今回は実装まで？ テストや実画面確認、デプロイも終わった感じ？",
            "used_tools": [],
            "persist": True,
            "model_route": {"kind": "project_completion_clarification", "model": None, "project_id": active["project_id"], "draft_expires_at": draft.get("expires_at")},
        }
    except Exception as exc:  # noqa: BLE001
        log.debug("project completion routing skipped: %s", exc)
        return None


def _latest_source_conversation_id(source_user_text: str) -> int | None:
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM conversations WHERE user_text=? ORDER BY id DESC LIMIT 1",
            (source_user_text,),
        ).fetchone()
    return int(row["id"]) if row else None


def commit_completion(
    *,
    user_id: str,
    project_id: str,
    stage: str,
    last_summary: str,
    event_type: str,
    event_summary: str,
    source_user_text: str,
    idempotency_key: str,
    next_action: str | None = None,
    blockers: list[str] | None = None,
    completed_evidence: list[str] | None = None,
    unverified_items: list[str] | None = None,
) -> dict[str, Any]:
    """Commit one approved completion preview idempotently."""
    ensure_completion_schema()
    with db.get_connection() as conn:
        existing = conn.execute("SELECT id FROM project_events WHERE idempotency_key=?", (idempotency_key,)).fetchone()
    if existing:
        checkpoint = project_continuity.get_project_checkpoint(user_id, project_id)
        return {"saved": True, "idempotency_hit": True, "event_id": int(existing["id"]), "checkpoint": checkpoint}

    source_conversation_id = _latest_source_conversation_id(source_user_text)
    checkpoint = project_continuity.save_project_checkpoint(
        user_id,
        project_id,
        stage=stage,
        last_summary=last_summary,
        next_action=next_action,
        blockers=blockers,
        completed_evidence=completed_evidence,
        unverified_items=unverified_items,
        last_session_ended_at=db.now_iso(),
        source_conversation_ids=[source_conversation_id] if source_conversation_id else None,
    )
    now = db.now_iso()
    payload = {
        "stage": stage,
        "next_action": next_action,
        "blockers": blockers or [],
        "completed_evidence": completed_evidence or [],
        "unverified_items": unverified_items or [],
        "source_user_text": source_user_text,
    }
    with db.get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO project_events (project_id, provider, event_type, summary, source_conversation_id, payload_json, idempotency_key, occurred_at, created_at) "
            "VALUES (?, 'petit', ?, ?, ?, ?, ?, ?, ?)",
            (project_id, event_type, event_summary, source_conversation_id, json.dumps(payload, ensure_ascii=False), idempotency_key, now, now),
        )
        event_id = int(cursor.lastrowid)
    _clear_draft(user_id)
    return {"saved": True, "idempotency_hit": False, "event_id": event_id, "checkpoint": checkpoint}
