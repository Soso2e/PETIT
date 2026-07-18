"""Build project resume messages from cached PETIT-owned state only.

Project resume is part of the interactive conversation path. It must never wait for
Notion, Linkraft, GitHub, or any other network source. Explicit sync commands update
those caches separately; this module only reads the latest saved state.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from . import db, project_completion, project_continuity


@dataclass
class ProjectResumeContext:
    project: dict[str, Any]
    checkpoint: dict[str, Any] | None = None
    recent_events: list[dict[str, Any]] = field(default_factory=list)
    updates_after_checkpoint: list[dict[str, Any]] = field(default_factory=list)
    recent_episodes: list[dict[str, Any]] = field(default_factory=list)
    legacy_handoff: dict[str, Any] | None = None
    verified_items: list[str] = field(default_factory=list)
    unverified_items: list[str] = field(default_factory=list)
    next_action: str | None = None
    blockers: list[str] = field(default_factory=list)
    source_freshness: dict[str, dict[str, Any]] = field(default_factory=dict)
    source_refresh: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def reference_counts(self) -> dict[str, Any]:
        return {
            "checkpoint": int(self.checkpoint is not None),
            "events": len(self.recent_events),
            "updates_after_checkpoint": len(self.updates_after_checkpoint),
            "episodes": len(self.recent_episodes),
            "legacy_handoff": int(self.legacy_handoff is not None),
            "sources": len(self.source_freshness),
            "stale_sources": sorted(
                provider for provider, state in self.source_freshness.items() if state.get("stale")
            ),
            "source_refresh_mode": self.source_refresh.get("mode", "cached_only"),
            "source_refresh_attempted": len(self.source_refresh.get("attempted") or []),
            "source_refresh_failed": list(self.source_refresh.get("failed") or []),
            "source_refresh_skipped": list(self.source_refresh.get("skipped") or []),
        }


def _cached_only_refresh_state() -> dict[str, Any]:
    return {
        "mode": "cached_only",
        "attempted": [],
        "failed": [],
        "skipped": [],
        "error": None,
    }


def _decode_json(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (json.JSONDecodeError, TypeError):
        return fallback


def _recent_project_events(project_id: str, limit: int) -> list[dict[str, Any]]:
    project_completion.ensure_completion_schema()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT id, provider, event_type, summary, source_conversation_id, payload_json, occurred_at, created_at "
            "FROM project_events WHERE project_id=? ORDER BY occurred_at DESC, id DESC LIMIT ?",
            (project_id, limit),
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        payload = _decode_json(item.pop("payload_json", "{}"), {})
        item["payload"] = payload if isinstance(payload, dict) else {}
        result.append(item)
    return result


def _recent_project_episodes(project_id: str, limit: int) -> list[dict[str, Any]]:
    project_continuity.ensure_project_schema()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT e.episode_id, e.started_at, e.ended_at, e.title, e.summary, e.decisions, e.facts, "
            "e.work_in_progress, e.next_action, l.relation, l.confidence, l.confirmed "
            "FROM episode_project_links l JOIN conversation_episodes e ON e.episode_id=l.episode_id "
            "WHERE l.project_id=? AND l.confirmed=1 "
            "ORDER BY e.ended_at DESC, CASE l.relation WHEN 'primary' THEN 0 WHEN 'dependency' THEN 1 "
            "WHEN 'referenced' THEN 2 ELSE 3 END, e.episode_id DESC LIMIT ?",
            (project_id, limit),
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for key in ("decisions", "facts", "work_in_progress", "next_action"):
            value = _decode_json(item.get(key), [])
            item[key] = value if isinstance(value, list) else []
        result.append(item)
    return result


def _project_aliases(project_id: str) -> set[str]:
    project_continuity.ensure_project_schema()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT normalized_alias FROM project_aliases WHERE project_id=?",
            (project_id,),
        ).fetchall()
    return {str(row["normalized_alias"]) for row in rows if row["normalized_alias"]}


def _legacy_handoff(project_id: str) -> dict[str, Any] | None:
    aliases = _project_aliases(project_id)
    if not aliases:
        return None
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM handoff_notes WHERE current_project IS NOT NULL ORDER BY id DESC LIMIT 50"
        ).fetchall()
    for row in rows:
        item = dict(row)
        normalized = project_continuity.normalize_alias(str(item.get("current_project") or ""))
        if normalized in aliases:
            return item
    return None


def _aggregate_source_states(provider: str) -> dict[str, Any]:
    all_states = db.all_sync_states()
    child_states = [
        state for state in all_states
        if str(state.get("source") or "").startswith(f"{provider}:")
    ]
    states = child_states or [state for state in all_states if state.get("source") == provider]
    if not states:
        states = [db.sync_state(provider)]

    successful = [str(state["last_success_at"]) for state in states if state.get("last_success_at")]
    failed = [str(state["last_failure_at"]) for state in states if state.get("last_failure_at")]
    errors = [
        f"{state.get('source')}: {state.get('last_error')}"
        for state in states
        if state.get("last_error")
    ]
    return {
        "stale": any(state.get("last_failure_at") and state.get("last_success_at") for state in states),
        "last_success_at": max(successful, default=None),
        "last_failure_at": max(failed, default=None),
        "error": "; ".join(errors) if errors else None,
        "sources": {
            str(state.get("source")): {
                "last_success_at": state.get("last_success_at"),
                "last_failure_at": state.get("last_failure_at"),
                "error": state.get("last_error"),
                "synced_count": state.get("synced_count"),
            }
            for state in states
        },
    }


def _source_freshness(project_id: str) -> dict[str, dict[str, Any]]:
    project_continuity.ensure_project_schema()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT provider FROM project_source_links "
            "WHERE project_id=? AND status='active' AND confirmed_at IS NOT NULL ORDER BY provider",
            (project_id,),
        ).fetchall()
    return {
        str(row["provider"]): _aggregate_source_states(str(row["provider"]))
        for row in rows
    }


def build_resume_context(
    user_id: str,
    project_id: str,
    *,
    event_limit: int = 5,
    episode_limit: int = 3,
) -> ProjectResumeContext:
    """Return immediately from saved state; never perform external I/O here."""
    project = project_continuity.get_project(project_id)
    if not project:
        raise ValueError("project not found")

    checkpoint = project_continuity.get_project_checkpoint(user_id, project_id)
    events = _recent_project_events(project_id, max(1, min(event_limit, 10)))
    episodes = _recent_project_episodes(project_id, max(1, min(episode_limit, 5)))
    handoff = _legacy_handoff(project_id)
    checkpoint_updated_at = str((checkpoint or {}).get("updated_at") or "")
    updates = [
        event for event in events
        if checkpoint_updated_at and str(event.get("occurred_at") or "") > checkpoint_updated_at
    ]

    verified = list((checkpoint or {}).get("completed_evidence") or [])
    unverified = list((checkpoint or {}).get("unverified_items") or [])
    blockers = list((checkpoint or {}).get("blockers") or [])
    next_action = str((checkpoint or {}).get("next_action") or "").strip() or None
    if not next_action and handoff:
        next_action = str(handoff.get("next_action") or "").strip() or None
    if not blockers and handoff and handoff.get("blockers"):
        raw = _decode_json(str(handoff.get("blockers")), None)
        blockers = (
            [str(item) for item in raw if str(item).strip()]
            if isinstance(raw, list)
            else [str(handoff["blockers"]).strip()]
        )

    return ProjectResumeContext(
        project=project,
        checkpoint=checkpoint,
        recent_events=events,
        updates_after_checkpoint=updates,
        recent_episodes=episodes,
        legacy_handoff=handoff,
        verified_items=verified,
        unverified_items=unverified,
        next_action=next_action,
        blockers=blockers,
        source_freshness=_source_freshness(project_id),
        source_refresh=_cached_only_refresh_state(),
    )


def _main_summary(context: ProjectResumeContext) -> str | None:
    checkpoint_summary = str((context.checkpoint or {}).get("last_summary") or "").strip()
    if checkpoint_summary:
        return checkpoint_summary
    if context.recent_events:
        summary = str(context.recent_events[0].get("summary") or "").strip()
        if summary:
            return summary
    primary = [item for item in context.recent_episodes if item.get("relation") == "primary"]
    for episode in [*primary, *context.recent_episodes]:
        summary = str(episode.get("summary") or "").strip()
        if summary:
            return summary
    if context.legacy_handoff:
        note = str(
            context.legacy_handoff.get("note")
            or context.legacy_handoff.get("stopped_at")
            or ""
        ).strip()
        if note:
            return note
    return None


def _compact_items(items: list[str], limit: int = 3) -> str:
    cleaned: list[str] = []
    for item in items:
        text = str(item).strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return "、".join(cleaned[:limit])


def render_resume_message(
    context: ProjectResumeContext,
    *,
    previous_project_name: str | None = None,
    same_project: bool = False,
) -> str:
    project_name = str(context.project["name"])
    if same_project:
        opening = f"お、{project_name}を続けるんだね。"
    elif previous_project_name:
        opening = f"{previous_project_name}から{project_name}に切り替えたよ。"
    else:
        opening = f"お、{project_name}を始めるんだね。"

    facts: list[str] = []
    summary = _main_summary(context)
    if summary:
        facts.append(f"前回は「{summary}」で止まってる。")

    verified = _compact_items(context.verified_items)
    unverified = _compact_items(context.unverified_items)
    if verified and unverified:
        facts.append(f"確認済みは{verified}、未確認は{unverified}。")
    elif verified:
        facts.append(f"確認済みは{verified}。")
    elif unverified:
        facts.append(f"未確認は{unverified}。")

    update_summaries = [
        str(item.get("summary") or "").strip()
        for item in context.updates_after_checkpoint
        if str(item.get("summary") or "").strip()
        and str(item.get("summary") or "").strip() != summary
    ]
    update_text = _compact_items(update_summaries, limit=2)
    if update_text:
        facts.append(f"その後のPETIT内更新は{update_text}。")

    blockers = _compact_items(context.blockers, limit=2)
    if blockers:
        facts.append(f"ブロッカーは{blockers}。")

    stale = [
        provider for provider, state in context.source_freshness.items()
        if state.get("stale")
    ]
    if stale:
        stale_text = "、".join(stale)
        facts.append(
            f"※ {stale_text}は最新同期に失敗。{stale_text}は前回成功時のキャッシュ。"
        )

    if context.next_action:
        facts.append(f"次は「{context.next_action}」の予定だった。")

    if not facts:
        return f"{opening}\n前回メモはまだないよ。今日はどこから始める？"
    return "\n".join([opening, *facts, "そこから進める？"])
