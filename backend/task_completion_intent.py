"""Deterministic resolution for named task-completion reports."""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from . import config, db, tools

_COMPLETION_PATTERNS = (
    re.compile(r"^(?P<target>.+?)(?:は|を)?(?:完了(?:した|しました|済み)?|終わ(?:った|りました)|終え(?:た|ました)|できた)[！!。\s]*$", re.IGNORECASE),
    re.compile(r"^(?P<target>.+?)(?:が)?(?:終わった|終わりました)[！!。\s]*$", re.IGNORECASE),
)
_PROJECT_MARKERS = ("project", "プロジェクト", "案件", "企画")
_NOISE_SUFFIXES = ("タスク", "作業")


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"[\s\-_・/\\.,。!！?？:：'\"()（）\[\]【】]+", "", text)
    text = text.replace("の", "").replace("を", "").replace("は", "")
    for suffix in _NOISE_SUFFIXES:
        if text.endswith(suffix.casefold()):
            text = text[: -len(suffix)]
    return text


def extract_target(message: str) -> str | None:
    text = unicodedata.normalize("NFKC", str(message or "")).strip()
    if not text:
        return None
    lowered = text.casefold()
    if any(marker in lowered for marker in _PROJECT_MARKERS):
        return None
    for pattern in _COMPLETION_PATTERNS:
        match = pattern.match(text)
        if match:
            target = match.group("target").strip(" 　、,")
            return target or None
    return None


def _score(query: str, title: str) -> int:
    q = _normalize(query)
    t = _normalize(title)
    if not q or not t:
        return 0
    if q == t:
        return 100
    if q in t:
        return 90 - min(20, len(t) - len(q))
    if t in q:
        return 80 - min(20, len(q) - len(t))
    query_parts = {part for part in re.split(r"[^0-9a-zぁ-んァ-ヶ一-龠]+", q) if part}
    title_parts = {part for part in re.split(r"[^0-9a-zぁ-んァ-ヶ一-龠]+", t) if part}
    overlap = query_parts & title_parts
    return 60 + len(overlap) if overlap else 0


def _candidate_rows(target: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT id, title, status, source, external_id, project_id "
            "FROM tasks_cache ORDER BY updated_at DESC, id DESC"
        ).fetchall()
    active: list[dict[str, Any]] = []
    completed: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        score = _score(target, str(item.get("title") or ""))
        if score < 70:
            continue
        item["match_score"] = score
        if str(item.get("status") or "").casefold() == str(config.NOTION_DONE_STATUS).casefold():
            completed.append(item)
        else:
            active.append(item)
    active.sort(key=lambda item: (-int(item["match_score"]), int(item["id"])))
    completed.sort(key=lambda item: (-int(item["match_score"]), int(item["id"])))
    return active, completed


def try_handle(message: str) -> dict[str, Any] | None:
    """Resolve a named task completion before project continuity or the LLM."""
    target = extract_target(message)
    if target is None:
        return None

    active, completed = _candidate_rows(target)
    if not active:
        if completed:
            title = str(completed[0]["title"])
            return {
                "reply": f"「{title}」はすでに完了になっています。",
                "used_tools": [],
                "persist": True,
                "model_route": _route("already_completed"),
            }
        return {
            "reply": f"「{target}」に一致する未完了タスクが見つかりませんでした。別の名前を短く教えてください。",
            "used_tools": [],
            "persist": True,
            "model_route": _route("no_candidate"),
        }

    best_score = int(active[0]["match_score"])
    best = [item for item in active if int(item["match_score"]) == best_score]
    if len(best) != 1:
        from . import dialogue_state, request_context
        session_id = request_context.current_ids()[1]
        candidates = [dialogue_state.entity(item, "mentioned") for item in best[:dialogue_state.MAX_FOCUS]]
        dialogue_state.set_pending(session_id, {"kind": "complete_task", "arguments": {}},
                                   [item for item in candidates if item], message)
        labels = "、".join(f"「{item['title']}」" for item in best[:5])
        return {
            "reply": f"候補が複数あります。どれを完了にしますか？ {labels}",
            "used_tools": [],
            "persist": True,
            "model_route": _route("multiple_candidates"),
        }

    task = best[0]
    title = str(task["title"])
    arguments = {"task_id": int(task["id"])}
    raw_result = tools.dispatch("complete_task", arguments)
    try:
        completion = json.loads(raw_result)
    except json.JSONDecodeError:
        completion = None
    failed = (
        raw_result.startswith("[error]")
        or not isinstance(completion, dict)
        or not completion.get("completed")
    )
    if failed:
        return {
            "reply": f"「{title}」を完了にできなかったよ。同期状態を確認して、もう一度試して。",
            "used_tools": [{"name": "complete_task", "arguments": arguments, "deterministic": True}],
            "persist": False,
            "model_route": _route("completion_failed"),
        }
    return {
        "reply": f"「{title}」を完了にしたよ。",
        "used_tools": [
            {"name": "get_tasks", "arguments": {"title_query": target}, "deterministic": True},
            {"name": "complete_task", "arguments": arguments, "deterministic": True},
        ],
        "persist": True,
        "model_route": _route("completed_unique_candidate"),
    }


def _route(reason: str) -> dict[str, Any]:
    return {
        "kind": "direct",
        "requested_route": "deterministic",
        "actual_route": "deterministic",
        "model": None,
        "tools": (
            ["get_tasks", "complete_task"]
            if reason in {"completed_unique_candidate", "completion_failed"}
            else []
        ),
        "reasons": [f"named_task_completion:{reason}"],
    }
