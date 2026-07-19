"""Task tools.

Reads/writes a local SQLite task cache (tasks_cache). Notion sync populates
this cache with source='notion'; local tasks use source='local'. Both are
returned by get_tasks so the LLM gets a unified view.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from .. import config, db, project_continuity
from ..notion_client import NotionError, create_task_page, update_task_page
from ..task_taxonomy import AREAS, AREA_LABELS, resolve_area
from .registry import tool

# Imported lazily to avoid circular import at module load time.
_notion_sync = None

_CATEGORIES = ["JobHunt", "Sch", "Life", "Work", "Hobby", "Event", "Create", "LiT"]
_PRIORITIES = ["Low", "Mid", "High"]


def _ensure_task_project_schema() -> None:
    from .. import notion_project_sync  # noqa: PLC0415

    notion_project_sync.ensure_notion_project_schema()


def _try_notion_sync() -> dict[str, Any]:
    """Silently sync from Notion if configured. Import lazily to avoid circular deps."""
    global _notion_sync
    if _notion_sync is None:
        from .notion import sync_if_configured  # noqa: PLC0415
        _notion_sync = sync_if_configured
    return _notion_sync()


def _confirmed_notion_project_external_id(project_id: str) -> str:
    """Resolve one confirmed Notion project source for an internal project."""
    _ensure_task_project_schema()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT external_id FROM project_source_links "
            "WHERE project_id=? AND provider='notion' AND status='active' AND confirmed_at IS NOT NULL "
            "ORDER BY updated_at DESC",
            (project_id,),
        ).fetchall()
    if not rows:
        raise ValueError("指定されたプロジェクトはNotionプロジェクトと確認済み紐付けがありません。")
    external_ids = {str(row["external_id"]) for row in rows}
    if len(external_ids) != 1:
        raise ValueError("指定されたプロジェクトに複数のNotion紐付けがあるため、1件に確定できません。")
    return next(iter(external_ids))


@tool(
    name="get_tasks",
    description=(
        "タスク一覧を取得する。Notion が設定されていれば自動で最新データを取得する。"
        "エリアは personal（個人）/ group（グループ）/ university（大学）/ work（仕事）。"
        "「今日のタスク教えて」「大学のやること何があったっけ」のような発話で使う。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "description": "絞り込むステータス。省略で未完了のみ、allで全件。",
            },
            "area": {
                "type": "string",
                "enum": list(AREAS),
                "description": "責任の発生源で絞り込む。個人/グループ/大学/仕事。",
            },
            "project_id": {
                "type": "string",
                "description": "確認済みPETIT内部プロジェクトIDで絞り込む。任意。",
            },
            "limit": {"type": "integer", "description": "最大件数", "default": 20},
        },
    },
)
def get_tasks(
    status: str | None = None,
    area: str | None = None,
    project_id: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    sync = _try_notion_sync()
    normalized_area, _ = resolve_area(area)

    sql = (
        "SELECT id, source, title, status, due_date, priority, category, area, reason, url, done_date, "
        "project_id, project_external_id FROM tasks_cache"
    )
    conditions: list[str] = []
    params: list[Any] = []
    if status and status.casefold() != "all":
        conditions.append("status = ?")
        params.append(status)
    elif not status:
        conditions.append("status != ?")
        params.append(config.NOTION_DONE_STATUS)
    if normalized_area:
        conditions.append("area = ?")
        params.append(normalized_area)
    if project_id:
        conditions.append("project_id = ?")
        params.append(project_id)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY (due_date IS NULL), due_date ASC LIMIT ?"
    params.append(max(1, min(int(limit), 100)))
    with db.get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    tasks = [dict(r) for r in rows]
    return {
        "count": len(tasks),
        "tasks": tasks,
        "filters": {"status": status, "area": normalized_area, "project_id": project_id},
        "sync": sync,
    }


@tool(
    name="add_task",
    description=(
        "新しいタスクを追加する旧名ツール。基本は create_task を使う。"
        "Notion には送らず、ローカルDBだけに保存する。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "タスクの内容"},
            "due_date": {"type": "string", "description": "期限（YYYY-MM-DD 等）。任意。"},
            "priority": {"type": "string", "description": "優先度（例: high, mid, low）。任意。"},
        },
        "required": ["title"],
    },
    requires_confirmation=True,
)
def add_task(title: str, due_date: str | None = None, priority: str | None = None) -> dict[str, Any]:
    with db.get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO tasks_cache (source, title, status, due_date, priority, updated_at) "
            "VALUES ('local', ?, 'todo', ?, ?, ?)",
            (title, due_date, priority, db.now_iso()),
        )
        task_id = int(cur.lastrowid)
    return {"added": True, "id": task_id, "title": title, "due_date": due_date, "priority": priority}


@tool(
    name="create_task",
    description=(
        "新しいタスクを作成する。Notion が設定されていれば Notion のタスクDBに作成し、"
        "未設定ならローカルDBに保存する。area は責任の発生源で、personal（個人）/ "
        "group（グループ）/ university（大学）/ work（仕事）から指定する。"
        "project_idを指定する場合、Notionでは確認済みRelationだけを使用する。"
        "areaが明確なら指定し、判断できない場合だけユーザーへ確認する。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "タスク名"},
            "due_date": {
                "type": "string",
                "description": "目標完了日時。YYYY-MM-DD または ISO datetime。作業予定とは別。",
            },
            "priority": {
                "type": "string",
                "enum": _PRIORITIES,
                "description": "優先度。迷う場合は Mid。",
            },
            "area": {
                "type": "string",
                "enum": list(AREAS),
                "description": "責任の発生源。personal/group/university/work。",
            },
            "project_id": {
                "type": "string",
                "description": "PETIT内部プロジェクトID。Notionでは確認済み紐付けがある場合だけRelationへ保存する。",
            },
            "category": {
                "type": "string",
                "enum": _CATEGORIES,
                "description": "旧Category。既存DB互換用。迷う場合は省略してよい。",
            },
            "reason": {"type": "string", "description": "補足・理由・メモ。任意。"},
        },
        "required": ["title"],
    },
    requires_confirmation=True,
)
def create_task(
    title: str,
    due_date: str | None = None,
    priority: str | None = None,
    area: str | None = None,
    project_id: str | None = None,
    category: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    priority = _normalize_option(priority, _PRIORITIES)
    category, category_source = _resolve_category(title, category, reason)
    area, area_source = resolve_area(area, category)

    if project_id:
        project_continuity.ensure_project_schema()
        if project_continuity.get_project(project_id) is None:
            return {
                "created": False,
                "error": "指定されたPETIT内部プロジェクトが見つかりません。",
                "project_id": project_id,
            }

    if config.notion_configured():
        project_external_ids: list[str] | None = None
        if project_id:
            try:
                project_external_ids = [_confirmed_notion_project_external_id(project_id)]
            except ValueError as exc:
                return {
                    "created": False,
                    "source": "notion",
                    "error": str(exc),
                    "project_id": project_id,
                    "message": "未確認プロジェクトをNotion Relationへ自動設定しませんでした。",
                }
        try:
            task = create_task_page(
                title=title,
                due_date=due_date,
                priority=priority or "Mid",
                categories=[category] if category else None,
                area=AREA_LABELS[area] if area else None,
                project_external_ids=project_external_ids,
                reason=reason,
            )
            _cache_task(task, source="notion", project_id=project_id)
            return {
                "created": True,
                "source": "notion",
                "task": task | {"project_id": project_id},
                "area_source": area_source,
                "category_source": category_source,
            }
        except NotionError as exc:
            return {
                "created": False,
                "source": "notion",
                "error": str(exc),
                "message": "Notionへの作成に失敗したため、ローカルへ代替保存していません。",
            }

    local = _create_local_task(title, due_date, priority, area, project_id, category, reason)
    return {
        "created": True,
        "source": "local",
        "task": local,
        "area_source": area_source,
        "category_source": category_source,
    }


@tool(
    name="complete_task",
    description=(
        "タスクを完了にする。task_id が分かる場合はそれを使う。分からない場合は title_query に"
        "タスク名の一部を指定する。Notion タスクなら Status=Done と Done=今日で更新する。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "task_id": {"type": "integer", "description": "PETIT のローカルキャッシュ数値ID。任意。"},
            "external_id": {"type": "string", "description": "NotionページUUID。分かる場合だけ使う。"},
            "title_query": {"type": "string", "description": "ユーザーがタスク名を指定した場合は、その名前をここへ入れる。"},
            "done_date": {"type": "string", "description": "完了日 YYYY-MM-DD。省略時は今日。"},
        },
    },
    requires_confirmation=True,
)
def complete_task(
    task_id: int | str | None = None,
    external_id: str | None = None,
    title_query: str | None = None,
    done_date: str | None = None,
) -> dict[str, Any]:
    if isinstance(task_id, str) and not task_id.isdigit():
        external_id = external_id or task_id
        task_id = None
    elif isinstance(task_id, str):
        task_id = int(task_id)
    task = _find_task(task_id=task_id, external_id=external_id, title_query=title_query)
    if task is None:
        candidates = _find_task_candidates(title_query) if title_query else []
        return {
            "completed": False,
            "error": "対象タスクを1件に絞れませんでした。タスク名をもう少し具体的に教えてください。",
            "candidates": candidates,
        }

    done = done_date or date.today().isoformat()
    if task["source"] == "notion" and task.get("external_id") and config.notion_configured():
        try:
            updated = update_task_page(
                page_id=task["external_id"],
                status=config.NOTION_DONE_STATUS,
                done_date=done,
            )
            _cache_task(updated, source="notion", project_id=task.get("project_id"))
            return {"completed": True, "source": "notion", "task": updated}
        except NotionError as exc:
            return {"completed": False, "source": "notion", "error": str(exc), "task": dict(task)}

    with db.get_connection() as conn:
        conn.execute(
            "UPDATE tasks_cache SET status=?, done_date=?, updated_at=? WHERE id=?",
            (config.NOTION_DONE_STATUS, done, db.now_iso(), task["id"]),
        )
    updated_local = {**dict(task), "status": config.NOTION_DONE_STATUS, "done_date": done}
    return {"completed": True, "source": "local", "task": updated_local}


def _normalize_option(value: str | None, allowed: list[str]) -> str | None:
    if not value:
        return None
    for option in allowed:
        if value.lower() == option.lower():
            return option
    return None


def _resolve_category(title: str, category: str | None, reason: str | None) -> tuple[str | None, str]:
    normalized = _normalize_option(category, _CATEGORIES)
    if normalized:
        return normalized, "explicit"

    text = f"{title} {reason or ''}".lower()
    rules = [
        ("JobHunt", ["就活", "面接", "履歴書", "es", "エントリー", "job", "career"]),
        ("Sch", ["学校", "大学", "授業", "課題", "レポート", "ゼミ", "sch"]),
        ("Life", ["掃除", "洗濯", "買い物", "病院", "役所", "生活", "家事"]),
        ("Work", ["仕事", "勤務", "mtg", "meeting", "業務", "work"]),
        ("Hobby", ["趣味", "ゲーム", "読書", "映画", "hobby"]),
        ("Event", ["予定", "イベント", "予約", "event", "ライブ"]),
        ("Create", ["実装", "開発", "制作", "デザイン", "記事", "create", "petit"]),
        ("LiT", ["lit", "life is tech"]),
    ]
    for name, keywords in rules:
        if any(k in text for k in keywords):
            return name, "auto_rule"
    return None, "unknown"


def _create_local_task(
    title: str,
    due_date: str | None,
    priority: str | None,
    area: str | None,
    project_id: str | None,
    category: str | None,
    reason: str | None,
) -> dict[str, Any]:
    _ensure_task_project_schema()
    now = db.now_iso()
    with db.get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO tasks_cache "
            "(source, title, status, due_date, priority, area, project_id, category, reason, updated_at) "
            "VALUES ('local', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (title, config.NOTION_DEFAULT_STATUS, due_date, priority or "Mid", area, project_id, category, reason, now),
        )
        task_id = int(cur.lastrowid)
    return {
        "id": task_id,
        "source": "local",
        "title": title,
        "status": config.NOTION_DEFAULT_STATUS,
        "due_date": due_date,
        "priority": priority or "Mid",
        "area": area,
        "project_id": project_id,
        "category": category,
        "reason": reason,
    }


def _cache_task(task: dict[str, Any], source: str, project_id: str | None = None) -> int:
    _ensure_task_project_schema()
    now = db.now_iso()
    external_id = task.get("external_id")
    area, _ = resolve_area(task.get("area"), task.get("category"))
    project_external_ids = [str(item) for item in task.get("project_external_ids") or [] if str(item).strip()]
    project_external_id = project_external_ids[0] if project_external_ids else task.get("project_external_id")
    with db.get_connection() as conn:
        existing = None
        if external_id:
            existing = conn.execute(
                "SELECT id FROM tasks_cache WHERE external_id = ?",
                (external_id,),
            ).fetchone()
        if existing:
            conn.execute(
                "UPDATE tasks_cache SET source=?, title=?, status=?, due_date=?, priority=?, "
                "area=?, category=?, reason=?, url=?, done_date=?, project_external_id=?, "
                "project_external_ids=?, project_id=COALESCE(?, project_id), updated_at=? WHERE id=?",
                (
                    source,
                    task["title"],
                    task["status"],
                    task.get("due_date"),
                    task.get("priority"),
                    area,
                    task.get("category"),
                    task.get("reason"),
                    task.get("url"),
                    task.get("done_date"),
                    project_external_id,
                    _json_list(project_external_ids),
                    project_id,
                    now,
                    existing["id"],
                ),
            )
            return int(existing["id"])
        cur = conn.execute(
            "INSERT INTO tasks_cache "
            "(source, title, status, due_date, priority, area, category, reason, external_id, url, done_date, "
            "project_external_id, project_external_ids, project_id, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                source,
                task["title"],
                task["status"],
                task.get("due_date"),
                task.get("priority"),
                area,
                task.get("category"),
                task.get("reason"),
                external_id,
                task.get("url"),
                task.get("done_date"),
                project_external_id,
                _json_list(project_external_ids),
                project_id,
                now,
            ),
        )
        return int(cur.lastrowid)


def _json_list(values: list[str]) -> str:
    import json

    return json.dumps(values, ensure_ascii=False)


def _find_task(task_id: int | None, external_id: str | None, title_query: str | None) -> dict[str, Any] | None:
    _try_notion_sync()
    with db.get_connection() as conn:
        if task_id is not None:
            row = conn.execute("SELECT * FROM tasks_cache WHERE id = ?", (task_id,)).fetchone()
            return dict(row) if row else None
        if external_id:
            row = conn.execute("SELECT * FROM tasks_cache WHERE external_id = ?", (external_id,)).fetchone()
            return dict(row) if row else None
        if title_query:
            rows = _find_task_rows(conn, title_query, limit=2)
            if len(rows) == 1:
                return dict(rows[0])
    return None


def _find_task_candidates(title_query: str | None) -> list[dict[str, Any]]:
    if not title_query:
        return []
    with db.get_connection() as conn:
        rows = _find_task_rows(conn, title_query, limit=5)
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "status": row["status"],
            "due_date": row["due_date"],
            "area": row["area"],
            "project_id": row["project_id"],
            "source": row["source"],
        }
        for row in rows
    ]


def _find_task_rows(conn: Any, title_query: str, limit: int) -> list[Any]:
    return conn.execute(
        "SELECT * FROM tasks_cache WHERE title LIKE ? "
        "ORDER BY (status = ?) ASC, (due_date IS NULL), due_date ASC, id DESC LIMIT ?",
        (f"%{title_query}%", config.NOTION_DONE_STATUS, limit),
    ).fetchall()
