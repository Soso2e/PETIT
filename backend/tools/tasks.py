"""Task tools.

Reads/writes a local SQLite task cache (tasks_cache). Notion sync populates
this cache with source='notion'; local tasks use source='local'. Both are
returned by get_tasks so the LLM gets a unified view.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from .. import config, db
from ..notion_client import NotionError, create_task_page, update_task_page
from .registry import tool

# Imported lazily to avoid circular import at module load time.
_notion_sync = None

_CATEGORIES = ["JobHunt", "Sch", "Life", "Work", "Hobby", "Event", "Create", "LiT"]
_PRIORITIES = ["Low", "Mid", "High"]


def _try_notion_sync() -> dict[str, Any]:
    """Silently sync from Notion if configured. Import lazily to avoid circular deps."""
    global _notion_sync
    if _notion_sync is None:
        from .notion import sync_if_configured  # noqa: PLC0415
        _notion_sync = sync_if_configured
    return _notion_sync()


@tool(
    name="get_tasks",
    description=(
        "タスク一覧を取得する。Notion が設定されていれば自動で最新データを取得する。"
        "「今日のタスク教えて」「やること何があったっけ」のような発話で使う。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "description": "絞り込むステータス。省略で未完了のみ、allで全件。",
            },
            "limit": {"type": "integer", "description": "最大件数", "default": 20},
        },
    },
)
def get_tasks(status: str | None = None, limit: int = 20) -> dict[str, Any]:
    sync = _try_notion_sync()

    sql = (
        "SELECT id, source, title, status, due_date, priority, category, reason, url, done_date "
        "FROM tasks_cache"
    )
    params: list[Any] = []
    if status and status.casefold() != "all":
        sql += " WHERE status = ?"
        params.append(status)
    elif not status:
        sql += " WHERE status != ?"
        params.append(config.NOTION_DONE_STATUS)
    sql += " ORDER BY (due_date IS NULL), due_date ASC LIMIT ?"
    params.append(limit)
    with db.get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    tasks = [dict(r) for r in rows]
    return {"count": len(tasks), "tasks": tasks, "sync": sync}


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
        "未設定ならローカルDBに保存する。分類が明らかなときだけ category を指定し、"
        "迷う場合はツールを呼ぶ前にユーザーへ確認する。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "タスク名"},
            "due_date": {
                "type": "string",
                "description": "期限または日時。YYYY-MM-DD または ISO datetime。任意。",
            },
            "priority": {
                "type": "string",
                "enum": _PRIORITIES,
                "description": "優先度。迷う場合は Mid。",
            },
            "category": {
                "type": "string",
                "enum": _CATEGORIES,
                "description": "分類。迷う場合は省略してよい。",
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
    category: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    priority = _normalize_option(priority, _PRIORITIES)
    category, category_source = _resolve_category(title, category, reason)

    if config.notion_configured():
        try:
            task = create_task_page(
                title=title,
                due_date=due_date,
                priority=priority or "Mid",
                categories=[category] if category else None,
                reason=reason,
            )
            _cache_task(task, source="notion")
            return {
                "created": True,
                "source": "notion",
                "task": task,
                "category_source": category_source,
            }
        except NotionError as exc:
            return {
                "created": False,
                "source": "notion",
                "error": str(exc),
                "message": "Notionへの作成に失敗したため、ローカルへ代替保存していません。",
            }

    local = _create_local_task(title, due_date, priority, category, reason)
    return {"created": True, "source": "local", "task": local, "category_source": category_source}


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
            _cache_task(updated, source="notion")
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
    category: str | None,
    reason: str | None,
) -> dict[str, Any]:
    now = db.now_iso()
    with db.get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO tasks_cache "
            "(source, title, status, due_date, priority, category, reason, updated_at) "
            "VALUES ('local', ?, ?, ?, ?, ?, ?, ?)",
            (title, config.NOTION_DEFAULT_STATUS, due_date, priority or "Mid", category, reason, now),
        )
        task_id = int(cur.lastrowid)
    return {
        "id": task_id,
        "source": "local",
        "title": title,
        "status": config.NOTION_DEFAULT_STATUS,
        "due_date": due_date,
        "priority": priority or "Mid",
        "category": category,
        "reason": reason,
    }


def _cache_task(task: dict[str, Any], source: str) -> int:
    now = db.now_iso()
    external_id = task.get("external_id")
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
                "category=?, reason=?, url=?, done_date=?, updated_at=? WHERE id=?",
                (
                    source,
                    task["title"],
                    task["status"],
                    task.get("due_date"),
                    task.get("priority"),
                    task.get("category"),
                    task.get("reason"),
                    task.get("url"),
                    task.get("done_date"),
                    now,
                    existing["id"],
                ),
            )
            return int(existing["id"])
        cur = conn.execute(
            "INSERT INTO tasks_cache "
            "(source, title, status, due_date, priority, category, reason, external_id, url, done_date, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                source,
                task["title"],
                task["status"],
                task.get("due_date"),
                task.get("priority"),
                task.get("category"),
                task.get("reason"),
                external_id,
                task.get("url"),
                task.get("done_date"),
                now,
            ),
        )
        return int(cur.lastrowid)


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
