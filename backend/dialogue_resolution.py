"""Narrow deterministic task dialogue, before project/capability routing."""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import timedelta
from typing import Any

from . import config, db, dialogue_state, request_context, task_hierarchy, time_context, tools

_REF = r"(?:その|それ|これ|こいつ|さっきの|前の|前者|後者|[12]番)"
_CHILD = re.compile(rf"^(?P<ref>{_REF})(?:の)?(?:子供|子ども|子タスク|子|下)に(?P<title>.+?)(?:を)?(?:追加|追加して|追加する|追加してほしい)[。!！]*$")
_CREATE = re.compile(r"^(?P<title>.+?)(?:という)?タスク(?:を)?(?:追加|追加して|追加する|追加してほしい)[。!！]*$")
_DUE = re.compile(rf"^(?P<ref>{_REF})(?:の)?(?:期限|締切)(?:を)?(?P<date>今日|明日|明後日|\d{{4}}-\d{{2}}-\d{{2}})(?:に)?(?:して|変更して|設定して)[。!！]*$")
_TITLE = re.compile(rf"^(?P<ref>{_REF})(?:の)?(?:名前|タスク名)(?:を)?(?P<title>.+?)に(?:して|変更して)[。!！]*$")
_COMPLETE = re.compile(rf"^(?P<ref>{_REF})(?:を|は)?(?:完了(?:して|にして|した)?|終わった)[。!！]*$")
_CANCEL = {"キャンセル", "やめて", "取り消し", "取消", "やめる"}


def _text(value: str) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip().rstrip("。!")


def _operation(text: str) -> tuple[dict[str, Any], str] | None:
    match = _CHILD.fullmatch(text)
    if match:
        return {"kind": "create_child_task", "title": match["title"].strip(" 「」")}, match["ref"]
    match = _DUE.fullmatch(text)
    if match:
        dates = {"今日": 0, "明日": 1, "明後日": 2}
        value = match["date"]
        if value in dates:
            value = (time_context.current_datetime().date() + timedelta(days=dates[value])).isoformat()
        else:
            from datetime import date
            try:
                date.fromisoformat(value)
            except ValueError:
                return None
        return {"kind": "update_task", "arguments": {"due_date": value}}, match["ref"]
    match = _TITLE.fullmatch(text)
    if match:
        return {"kind": "update_task", "arguments": {"title": match["title"].strip(" 「」")}}, match["ref"]
    match = _COMPLETE.fullmatch(text)
    if match:
        return {"kind": "complete_task", "arguments": {}}, match["ref"]
    return None


def _live_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Resolve stable IDs again. Never substitute another task by matching its title."""
    result = []
    seen = set()
    for item in items[:dialogue_state.MAX_FOCUS]:
        if not isinstance(item, dict) or item.get("entity_type") != "task":
            continue
        ref = dialogue_state.entity(item, "mentioned")
        if not ref or ref["entity_id"] in seen:
            continue
        task = task_hierarchy._find_task(ref["entity_id"])
        if not task or str(task.get("source") or "local") != str(item.get("source") or "local"):
            continue
        ref.update(title=task["title"], role=item.get("role", "mentioned"), turn_id=item.get("turn_id"))
        result.append(ref)
        seen.add(ref["entity_id"])
    return result


def select(answer: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    text = re.sub(r"^やっぱり\s*", "", _text(answer)).strip(" 「」")
    ordinal = {"前者": 0, "後者": 1, "1番": 0, "2番": 1}
    if text in ordinal:
        index = ordinal[text]
        # Former/latter is only meaningful for an explicitly presented pair.
        if text in {"前者", "後者"} and len(candidates) != 2:
            return None
        return candidates[index] if index < len(candidates) else None
    if text in {"その", "それ", "これ", "こいつ", "さっきの"}:
        return candidates[0] if len(candidates) == 1 else None
    numbered = re.fullmatch(r"([1-8])(?:番目|番)(?:の)?(?:タスク)?", text)
    if numbered:
        index = int(numbered[1]) - 1
        return candidates[index] if index < len(candidates) else None
    task_id = re.fullmatch(r"(?:ID[:： ]*|#)?(\d+)", text, re.IGNORECASE)
    matches = [item for item in candidates if (str(item["entity_id"]) == task_id[1] if task_id else _text(item["title"]) == text)]
    return matches[0] if len(matches) == 1 else None


def _focus(ref: str, state: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str]:
    stack = _live_candidates(state.get("focus_stack") or [])
    primary = [item for item in stack if item.get("role") != "parent"]
    if not primary:
        return None, [], "missing_focus"
    if ref in {"前者", "後者", "1番", "2番"}:
        # Ordinals refer only to explicitly saved candidate order, not recency.
        return None, primary, "candidate_order_required"
    if ref == "前の":
        earlier = [item for item in primary if item.get("turn_id") != primary[-1].get("turn_id")]
        if earlier:
            group = [item for item in earlier if item.get("turn_id") == earlier[-1].get("turn_id")]
            return (group[0] if len(group) == 1 else None), group, "previous_focus"
        return None, primary, "ambiguous_previous_focus"
    latest = primary[-1]
    group = [item for item in primary if item.get("turn_id") == latest.get("turn_id")]
    if len(group) == 1:
        return latest, primary, "last_selected" if latest["role"] == "last_selected" else "last_tool_result"
    return None, group, "ambiguous_focus"


def _reply(text: str, source: str, used: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"reply": text, "used_tools": used or [], "persist": True,
            "model_route": {"kind": "dialogue", "requested_route": "deterministic", "actual_route": "deterministic",
                            "model": None, "llm_call_count": 0, "dialogue_state_used": True, "dialogue_resolution_source": source}}


def _question(candidates: list[dict[str, Any]]) -> str:
    if not candidates:
        return "対象を特定できませんでした。タスク名またはIDを教えてください。"
    labels = " / ".join(f"{i}. {item['title']} (ID:{item['entity_id']})" for i, item in enumerate(candidates, 1))
    return f"どのタスクにする？ {labels}"


def _dispatch(name: str, arguments: dict[str, Any], used: list[dict[str, Any]]) -> dict[str, Any]:
    # This path only supports the established reversible task writes. If policy
    # changes, refuse immediate execution instead of bypassing confirmation.
    if tools.risk_for(name) != "low_risk_write":
        return {"error": "この操作は確認が必要です。明示的なタスク操作として依頼してください。"}
    raw = tools.dispatch(name, arguments)
    used.append({"name": name, "arguments": arguments, "deterministic": True})
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {"error": str(raw)}
    if not isinstance(data, dict) or any(data.get(key) is False for key in ("created", "updated", "completed")):
        return {"error": str(raw)}
    return data


def _execute(operation: dict[str, Any], chosen: dict[str, Any], session_id: str, source: str) -> dict[str, Any]:
    task = task_hierarchy._find_task(chosen["entity_id"])
    if not task or task.get("source", "local") != chosen.get("source", "local"):
        return _reply("対象タスクが見つかりませんでした。タスク名またはIDを指定し直してください。", "stale_candidate")
    used = []
    kind = operation["kind"]
    if kind == "select_task":
        item = dialogue_state.entity(task, "last_selected", turn_id=request_context.current_ids()[0])
        dialogue_state.remember(session_id, [item])
        return _reply(f"「{task['title']}」を選んだよ。", source)
    if kind == "create_child_task":
        # Validate before creating, so an invalid parent cannot leave an orphan.
        error = task_hierarchy._validate_parent({"id": -1, "source": "notion" if config.notion_configured() else "local"}, task)
        if error:
            return _reply(error, "invalid_parent")
        data = _dispatch("create_task", {"title": operation["title"]}, used)
        if data.get("error"):
            return _reply(f"タスクを追加できませんでした。{data['error']}", source, used)
        child = data.get("task") or {}
        if not child.get("id"):
            return _reply("作成結果のタスクIDを取得できませんでした。タスク一覧を確認してください。", source, used)
        linked = _dispatch("set_task_parent", {"task_id": child["id"], "parent_task_id": task["id"]}, used)
        if linked.get("error"):
            return _reply(f"「{child['title']}」は追加しましたが、親子設定に失敗しました。{linked['error']}", source, used)
        return _reply(f"「{task['title']}」の子に「{child['title']}」を追加したよ。", source, used)
    if kind not in {"update_task", "complete_task"}:
        return _reply("確認待ちの操作を読み取れませんでした。依頼を指定し直してください。", "invalid_pending")
    data = _dispatch(kind, {**operation.get("arguments", {}), "task_id": task["id"]}, used)
    if data.get("error"):
        return _reply(f"タスクを変更できませんでした。{data['error']}", source, used)
    return _reply(f"「{(data.get('task') or task)['title']}」を{'完了にした' if kind == 'complete_task' else '変更した'}よ。", source, used)


def try_handle(message: str) -> dict[str, Any] | None:
    _, session_id = request_context.current_ids()
    if not session_id:
        return None
    text = _text(message)
    state = dialogue_state.load(session_id)
    pending = state.get("pending_dialogue")
    operation = _operation(text)
    if pending and pending.get("owner") == "tasks":
        if text in _CANCEL:
            dialogue_state.take_pending(session_id, pending["id"])
            return _reply("確認待ちの操作をキャンセルしたよ。", "pending_cancel")
        saved_candidates = pending.get("candidates") or []
        if not saved_candidates:
            # Missing focus: a subsequent exact name/ID is explicit selection,
            # not a global fuzzy replacement or a Memory/BRAIN lookup.
            with db.get_connection() as conn:
                rows = conn.execute("SELECT id, title, source FROM tasks_cache WHERE title=? OR CAST(id AS TEXT)=? ORDER BY id LIMIT ?",
                                    (text.strip("「」"), re.sub(r"^(?:ID[:： ]*|#)", "", text, flags=re.I), dialogue_state.MAX_FOCUS)).fetchall()
            saved_candidates = [dialogue_state.entity(dict(row), "mentioned") for row in rows]
            saved_candidates = [item for item in saved_candidates if item]
            if len(saved_candidates) > 1:
                dialogue_state.set_pending(session_id, pending["operation"], saved_candidates, pending["original_request"])
                return _reply(_question(saved_candidates), "ambiguous_name")
        # Keep original order for ordinal replies; revalidate only after selection.
        chosen = select(text, saved_candidates)
        if chosen:
            if not dialogue_state.take_pending(session_id, pending["id"]):
                return _reply("確認状態を更新できませんでした。もう一度依頼してください。", "pending_unavailable")
            return _execute(pending["operation"], chosen, session_id, "pending_dialogue")
        if not operation and not _CREATE.fullmatch(text):
            # A new explicit topic can leave the clarification; a short candidate
            # answer belongs to its owner and must never reach the project router.
            from . import project_router
            if project_router._parse_action(text) or len(text) > 80 or any(marker in text for marker in ("天気", "何時", "教えて", "ところで", "別の話")):
                dialogue_state.take_pending(session_id, pending["id"])
                return None
            return _reply(_question(saved_candidates), "pending_unresolved")
        dialogue_state.take_pending(session_id, pending["id"])
    if operation:
        op, ref = operation
        chosen, candidates, source = _focus(ref, state)
        if chosen:
            return _execute(op, chosen, session_id, source)
        dialogue_state.set_pending(session_id, op, candidates, message)
        return _reply(_question(candidates), source)
    match = _CREATE.fullmatch(text)
    if match:
        used = []
        data = _dispatch("create_task", {"title": match["title"].strip(" 「」")}, used)
        if data.get("error"):
            return _reply(f"タスクを追加できませんでした。{data['error']}", "explicit_task", used)
        return _reply(f"「{data['task']['title']}」をタスクとして追加したよ。", "explicit_task", used)
    if re.fullmatch(_REF, text) and state.get("focus_stack"):
        chosen, candidates, source = _focus(text, state)
        if chosen:
            return _execute({"kind": "select_task"}, chosen, session_id, source)
        dialogue_state.set_pending(session_id, {"kind": "select_task"}, candidates, message)
        return _reply(_question(candidates), source)
    if re.match(rf"^{_REF}(?:の)?(?:期限|締切|子供|子ども|子タスク|子|下|名前|タスク名)", text):
        return _reply("対象と変更内容を確認したい。タスク名と期限・追加内容を具体的に教えてください。", "unsupported_task_anaphora")
    return None
