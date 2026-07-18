"""Deterministic project intent resolution and switching for PETIT.

The router only handles explicit project-work utterances. Ordinary chat remains on
PETIT's existing fast path, and ambiguous aliases never change active state.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Literal

from . import db, project_continuity, project_registration, project_resume

log = logging.getLogger(__name__)

ResolutionKind = Literal["resolved", "ambiguous", "new_candidate", "none"]

_ACTION_PATTERN = re.compile(
    r"^(?P<target>.+?)(?:を|に)?"
    r"(?P<action>やる|進める|再開(?:する)?|戻る|開発(?:する)?|作業(?:する)?|続ける|取りかかる)"
    r"(?:よ|ね|わ|ぞ|かな|か)?[。．.!！?？]*$",
    re.IGNORECASE,
)
_PREFIX_PATTERN = re.compile(
    r"^(?:じゃあ|じゃ|では|それじゃ|そしたら|次は|今日は|今日|今から|これから|まずは|まず)\s*",
    re.IGNORECASE,
)
_ACTIVE_CONTEXT_TARGETS = {
    "これ",
    "それ",
    "あれ",
    "このプロジェクト",
    "この作業",
    "さっきの",
    "さっきの続き",
    "前の",
    "前の続き",
    "続き",
}
_AMBIGUOUS_CONTEXT_TARGETS = {"次", "次のやつ", "別のやつ", "どれか", "何か"}
_PROJECT_ORIENTED_ACTIONS = {
    "進める",
    "再開",
    "再開する",
    "戻る",
    "開発",
    "開発する",
    "作業",
    "作業する",
    "続ける",
    "取りかかる",
}


@dataclass(frozen=True)
class ProjectResolution:
    kind: ResolutionKind
    project_id: str | None = None
    candidates: tuple[dict[str, Any], ...] = ()
    matched_alias: str | None = None
    confidence: float | None = None
    reason: str = ""
    target_text: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "project_id": self.project_id,
            "candidates": [dict(item) for item in self.candidates],
            "matched_alias": self.matched_alias,
            "confidence": self.confidence,
            "reason": self.reason,
            "target_text": self.target_text,
        }


def _clean_target(value: str) -> str:
    target = value.strip(" \t\r\n、,。．.!！?？「」『』\"'")
    previous = None
    while target and previous != target:
        previous = target
        target = _PREFIX_PATTERN.sub("", target).strip()
    target = re.sub(r"(?:という)?プロジェクト$", "", target, flags=re.IGNORECASE).strip()
    return target


def _parse_action(message: str) -> tuple[str, str] | None:
    compact = " ".join(message.strip().split())
    match = _ACTION_PATTERN.fullmatch(compact)
    if not match:
        if re.fullmatch(r"(?:さっきの|前の)?続き(?:を)?(?:やる|進める|再開(?:する)?)?[。．.!！?？]*", compact):
            return "続き", "続ける"
        return None
    return _clean_target(match.group("target")), match.group("action")


def _alias_rows() -> list[dict[str, Any]]:
    project_continuity.ensure_project_schema()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT p.id, p.name, p.status, p.description, p.updated_at, "
            "a.alias, a.normalized_alias FROM project_aliases a "
            "JOIN projects p ON p.id=a.project_id "
            "WHERE p.status != 'archived' ORDER BY length(a.normalized_alias) DESC, p.updated_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def _dedupe_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        project_id = str(row["id"])
        if project_id in seen:
            continue
        seen.add(project_id)
        result.append(
            {
                "id": project_id,
                "name": row["name"],
                "matched_alias": row.get("alias"),
                "description": row.get("description"),
            }
        )
    return result


def _match_alias(target: str) -> tuple[list[dict[str, Any]], str | None, float | None]:
    normalized_target = project_continuity.normalize_alias(target)
    if not normalized_target:
        return [], None, None
    rows = _alias_rows()
    exact = [row for row in rows if row["normalized_alias"] == normalized_target]
    if exact:
        candidates = _dedupe_candidates(exact)
        return candidates, str(exact[0]["alias"]), 1.0

    contained = [
        row
        for row in rows
        if len(str(row["normalized_alias"])) >= 2 and str(row["normalized_alias"]) in normalized_target
    ]
    if not contained:
        return [], None, None
    longest = max(len(str(row["normalized_alias"])) for row in contained)
    strongest = [row for row in contained if len(str(row["normalized_alias"])) == longest]
    candidates = _dedupe_candidates(strongest)
    return candidates, str(strongest[0]["alias"]), 0.95


def resolve_project(
    user_message: str,
    *,
    user_id: str,
    recent_history: list[dict[str, str]] | None = None,
) -> ProjectResolution:
    """Resolve an explicit project-work utterance without using an LLM."""
    del recent_history  # Reserved for a later bounded context candidate list.
    parsed = _parse_action(user_message)
    if parsed is None:
        return ProjectResolution(kind="none", reason="no_project_action")

    target, action = parsed
    active = project_continuity.get_active_project(user_id)
    if not target:
        return ProjectResolution(kind="none", reason="empty_target")

    candidates, matched_alias, confidence = _match_alias(target)
    if len(candidates) == 1:
        return ProjectResolution(
            kind="resolved",
            project_id=str(candidates[0]["id"]),
            candidates=tuple(candidates),
            matched_alias=matched_alias,
            confidence=confidence,
            reason="confirmed_alias",
            target_text=target,
        )
    if len(candidates) > 1:
        return ProjectResolution(
            kind="ambiguous",
            candidates=tuple(candidates),
            matched_alias=matched_alias,
            confidence=confidence,
            reason="alias_collision",
            target_text=target,
        )

    normalized_target = project_continuity.normalize_alias(target)
    active_context = {project_continuity.normalize_alias(item) for item in _ACTIVE_CONTEXT_TARGETS}
    ambiguous_context = {project_continuity.normalize_alias(item) for item in _AMBIGUOUS_CONTEXT_TARGETS}
    if normalized_target in active_context:
        if active:
            candidate = {
                "id": active["project_id"],
                "name": active["name"],
                "matched_alias": None,
                "description": active.get("description"),
            }
            return ProjectResolution(
                kind="resolved",
                project_id=str(active["project_id"]),
                candidates=(candidate,),
                confidence=0.85,
                reason="active_project_context",
                target_text=target,
            )
        return ProjectResolution(kind="ambiguous", reason="active_project_missing", target_text=target)
    if normalized_target in ambiguous_context:
        return ProjectResolution(kind="ambiguous", reason="recent_candidate_missing", target_text=target)

    contains_ascii_name = bool(re.search(r"[A-Za-z0-9_-]", target))
    project_oriented = action in _PROJECT_ORIENTED_ACTIONS or "プロジェクト" in user_message
    if contains_ascii_name or project_oriented:
        return ProjectResolution(kind="new_candidate", reason="unregistered_explicit_name", target_text=target)
    return ProjectResolution(kind="none", reason="ordinary_activity_not_project", target_text=target)


def _ambiguous_reply(resolution: ProjectResolution) -> str:
    names = [str(item.get("name") or "名称未設定") for item in resolution.candidates]
    if names:
        quoted = "、".join(f"「{name}」" for name in names[:5])
        return f"どのプロジェクトか確認したい。候補は{quoted}。どれを進める？"
    return "どのプロジェクトのことかまだ絞れない。プロジェクト名を教えて。"


def handle_project_turn(
    user_message: str,
    *,
    user_id: str,
    recent_history: list[dict[str, str]] | None = None,
) -> dict[str, Any] | None:
    """Resolve, switch and render a direct project response when applicable."""
    resolution = resolve_project(user_message, user_id=user_id, recent_history=recent_history)
    route = {"kind": "project_continuity", "model": None, "project_resolution": resolution.as_dict()}
    if resolution.kind == "none":
        return None
    if resolution.kind == "ambiguous":
        return {
            "reply": _ambiguous_reply(resolution),
            "used_tools": [],
            "persist": True,
            "model_route": route,
        }
    if resolution.kind == "new_candidate":
        name = resolution.target_text or "その名前"
        return project_registration.preview_new_project(name, user_id=user_id)

    previous = project_continuity.get_active_project(user_id)
    active = project_continuity.set_active_project(user_id, resolution.project_id)
    if not active:
        return None
    same_project = bool(previous and previous["project_id"] == active["project_id"])
    context = project_resume.build_resume_context(user_id, str(active["project_id"]))
    reply = project_resume.render_resume_message(
        context,
        previous_project_name=str(previous["name"]) if previous and not same_project else None,
        same_project=same_project,
    )
    return {
        "reply": reply,
        "used_tools": [],
        "persist": True,
        "model_route": route
        | {
            "previous_project_id": previous["project_id"] if previous else None,
            "active_project_id": active["project_id"],
            "resume_references": context.reference_counts(),
        },
    }


def try_handle_project_turn(
    user_message: str,
    *,
    user_id: str,
    recent_history: list[dict[str, str]] | None = None,
) -> dict[str, Any] | None:
    """Best-effort entrypoint for registration, completion, and switching."""
    try:
        registration = project_registration.try_handle_registration_turn(
            user_message,
            user_id=user_id,
        )
        if registration:
            return registration
        from . import project_completion

        completion = project_completion.try_handle_completion_turn(
            user_message,
            user_id=user_id,
            recent_history=recent_history,
        )
        if completion:
            return completion
        return handle_project_turn(user_message, user_id=user_id, recent_history=recent_history)
    except Exception as exc:  # noqa: BLE001
        log.debug("project routing skipped: %s", exc)
        return None
