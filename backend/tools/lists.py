"""Generic list registry and local list items.

The built-in task list is surfaced alongside user-created collections so PETIT can
describe every available list with its storage source. Custom collections are
stored locally for now; the source field keeps the model ready for future Notion
database links.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .. import config, db
from .registry import tool

_TASK_LIST_ID = "tasks"
_TASK_ALIASES = frozenset({"task", "tasks", "todo", "タスク", "やること"})
_SUPPORTED_SOURCES = frozenset({"local"})


def ensure_list_schema() -> None:
    with db.get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS list_collections (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT NOT NULL,
                normalized_name TEXT NOT NULL UNIQUE,
                description     TEXT,
                source          TEXT NOT NULL DEFAULT 'local',
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS list_items (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                collection_id INTEGER NOT NULL REFERENCES list_collections(id) ON DELETE CASCADE,
                title         TEXT NOT NULL,
                status        TEXT NOT NULL DEFAULT 'active',
                note          TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_list_items_collection_status
            ON list_items(collection_id, status, id);
            """
        )


def _clean_name(value: Any) -> str:
    name = str(value or "").strip(" \t\r\n　、。,.!！?？『』「」\"'")
    for suffix in ("のリスト", "リスト", "一覧"):
        if name.endswith(suffix) and len(name) > len(suffix):
            name = name[: -len(suffix)].rstrip(" 　")
            break
    if not name:
        raise ValueError("リスト名を指定してください。")
    if len(name) > 80:
        raise ValueError("リスト名は80文字以内にしてください。")
    return name


def _normalize_name(value: Any) -> str:
    cleaned = _clean_name(value)
    return re.sub(r"[\s　_・\-]+", "", cleaned).casefold()


def _source_label(source: str) -> str:
    return "Notion" if source == "notion" else "ローカル"


def _task_list() -> dict[str, Any]:
    source = "notion" if config.notion_configured() else "local"
    with db.get_connection() as conn:
        item_count = int(conn.execute("SELECT COUNT(*) FROM tasks_cache").fetchone()[0])
    return {
        "id": _TASK_LIST_ID,
        "name": "タスク",
        "display_name": "タスク",
        "normalized_name": "タスク",
        "kind": "task",
        "source": source,
        "source_label": _source_label(source),
        "item_count": item_count,
        "built_in": True,
    }


def _custom_list_payload(row: Any) -> dict[str, Any]:
    source = str(row["source"] or "local")
    return {
        "id": int(row["id"]),
        "name": str(row["name"]),
        "display_name": f"{row['name']}リスト",
        "normalized_name": str(row["normalized_name"]),
        "description": row["description"],
        "kind": "custom",
        "source": source,
        "source_label": _source_label(source),
        "item_count": int(row["item_count"] or 0),
        "built_in": False,
    }


def _find_custom_list(
    *,
    list_id: int | str | None = None,
    list_name: str | None = None,
) -> dict[str, Any] | None:
    ensure_list_schema()
    with db.get_connection() as conn:
        if list_id is not None and str(list_id).strip().isdigit():
            row = conn.execute(
                "SELECT id, name, normalized_name, description, source, 0 AS item_count "
                "FROM list_collections WHERE id=?",
                (int(str(list_id).strip()),),
            ).fetchone()
        elif list_name:
            row = conn.execute(
                "SELECT id, name, normalized_name, description, source, 0 AS item_count "
                "FROM list_collections WHERE normalized_name=?",
                (_normalize_name(list_name),),
            ).fetchone()
        else:
            row = None
    return _custom_list_payload(row) if row else None


@tool(
    name="get_lists",
    description=(
        "PETITで使えるリスト一覧を保存先つきで取得する。"
        "組み込みのタスク一覧と、ユーザーが作成したアニメ・映画・買い物などのカスタムリストを返す。"
        "『新しいリストを作りたい』『どんなリストがある？』で最初に使う。"
    ),
    parameters={"type": "object", "properties": {}},
)
def get_lists() -> dict[str, Any]:
    ensure_list_schema()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT c.id, c.name, c.normalized_name, c.description, c.source, "
            "COUNT(i.id) AS item_count "
            "FROM list_collections AS c "
            "LEFT JOIN list_items AS i ON i.collection_id=c.id "
            "GROUP BY c.id "
            "ORDER BY c.id"
        ).fetchall()
    lists = [_task_list(), *[_custom_list_payload(row) for row in rows]]
    return {
        "count": len(lists),
        "lists": lists,
        "response_guidance": (
            "リスト名の後ろにsource_labelを添えて説明する。"
            "例: タスク（Notion）、アニメリスト（ローカル）。"
            "新規作成の保存先は現時点ではローカルSQLite。"
        ),
    }


@tool(
    name="create_list",
    description=(
        "タスクではない新しいカスタムリストを作成する。"
        "アニメ・映画・買い物・読みたい本などの一覧向け。"
        "現時点ではローカルSQLiteへ保存し、同名リストと組み込みのタスクは重複作成しない。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "リスト名。『アニメリスト』なら『アニメ』でもよい。"},
            "description": {"type": "string", "description": "用途の説明。任意。"},
            "source": {
                "type": "string",
                "enum": ["local"],
                "default": "local",
                "description": "保存先。MVPではlocalのみ。",
            },
        },
        "required": ["name"],
    },
    requires_confirmation=True,
)
def create_list(
    name: str,
    description: str | None = None,
    source: str = "local",
) -> dict[str, Any]:
    ensure_list_schema()
    cleaned_name = _clean_name(name)
    normalized_name = _normalize_name(cleaned_name)
    normalized_source = str(source or "local").strip().casefold()
    if normalized_name in _TASK_ALIASES:
        return {
            "created": False,
            "error": "タスクは組み込みリストとして既にあります。",
            "existing_list": _task_list(),
        }
    if normalized_source not in _SUPPORTED_SOURCES:
        return {
            "created": False,
            "error": "この保存先にはまだリストを作成できません。",
            "supported_sources": sorted(_SUPPORTED_SOURCES),
        }

    now = db.now_iso()
    with db.get_connection() as conn:
        existing = conn.execute(
            "SELECT id, name, normalized_name, description, source, 0 AS item_count "
            "FROM list_collections WHERE normalized_name=?",
            (normalized_name,),
        ).fetchone()
        if existing:
            return {
                "created": False,
                "duplicate": True,
                "list": _custom_list_payload(existing),
            }
        cur = conn.execute(
            "INSERT INTO list_collections "
            "(name, normalized_name, description, source, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (cleaned_name, normalized_name, description, normalized_source, now, now),
        )
        list_id = int(cur.lastrowid)

    return {
        "created": True,
        "list": {
            "id": list_id,
            "name": cleaned_name,
            "display_name": f"{cleaned_name}リスト",
            "normalized_name": normalized_name,
            "description": description,
            "kind": "custom",
            "source": normalized_source,
            "source_label": _source_label(normalized_source),
            "item_count": 0,
            "built_in": False,
        },
    }


@tool(
    name="get_list_items",
    description=(
        "指定したリストの中身を取得する。list_idまたはlist_nameのどちらかを指定する。"
        "タスクを指定した場合は既存の統合タスク一覧を使い、カスタムリストはローカルSQLiteから返す。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "list_id": {"type": "string", "description": "リストID。タスクはtasks。"},
            "list_name": {"type": "string", "description": "リスト名。例: アニメ、アニメリスト、タスク。"},
            "status": {"type": "string", "description": "カスタム項目またはタスクの状態で絞り込む。任意。"},
            "limit": {"type": "integer", "default": 50, "description": "最大件数。"},
        },
    },
)
def get_list_items(
    list_id: int | str | None = None,
    list_name: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    bounded_limit = max(1, min(int(limit), 100))
    target_name = _normalize_name(list_name) if list_name else ""
    if str(list_id or "").strip().casefold() == _TASK_LIST_ID or target_name in _TASK_ALIASES:
        from . import task_reads  # noqa: PLC0415

        result = task_reads.get_tasks(
            status=status,
            priority="all",
            limit=bounded_limit,
        )
        return {
            "list": _task_list(),
            "count": result["returned_count"],
            "items": result["tasks"],
            "has_more": result["has_more"],
            "status_summary": result["status_summary"],
            "sync": result["sync"],
        }

    collection = _find_custom_list(list_id=list_id, list_name=list_name)
    if collection is None:
        return {
            "found": False,
            "error": "対象のリストが見つかりません。",
            "list_id": list_id,
            "list_name": list_name,
        }

    conditions = ["collection_id=?"]
    params: list[Any] = [collection["id"]]
    if status:
        conditions.append("LOWER(TRIM(status))=?")
        params.append(str(status).strip().casefold())
    where = " WHERE " + " AND ".join(conditions)
    with db.get_connection() as conn:
        total_count = int(
            conn.execute("SELECT COUNT(*) FROM list_items" + where, params).fetchone()[0]
        )
        rows = conn.execute(
            "SELECT id, title, status, note, metadata_json, created_at, updated_at "
            "FROM list_items"
            + where
            + " ORDER BY id ASC LIMIT ?",
            [*params, bounded_limit],
        ).fetchall()

    items = []
    for row in rows:
        item = dict(row)
        try:
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        except json.JSONDecodeError:
            item["metadata"] = {}
        items.append(item)
    return {
        "found": True,
        "list": collection,
        "count": len(items),
        "total_count": total_count,
        "has_more": len(items) < total_count,
        "items": items,
    }


@tool(
    name="add_list_item",
    description=(
        "カスタムリストへ項目を追加する。例: アニメリストへ『葬送のフリーレン』を追加する。"
        "組み込みのタスクへ追加する場合はcreate_taskを使う。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "list_id": {"type": "string", "description": "カスタムリストID。任意。"},
            "list_name": {"type": "string", "description": "カスタムリスト名。任意。"},
            "title": {"type": "string", "description": "追加する項目名。"},
            "status": {"type": "string", "default": "active", "description": "項目の状態。"},
            "note": {"type": "string", "description": "メモ。任意。"},
            "metadata": {"type": "object", "description": "評価・URLなどの追加情報。任意。"},
        },
        "required": ["title"],
    },
    requires_confirmation=True,
)
def add_list_item(
    title: str,
    list_id: int | str | None = None,
    list_name: str | None = None,
    status: str = "active",
    note: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target_name = _normalize_name(list_name) if list_name else ""
    if str(list_id or "").strip().casefold() == _TASK_LIST_ID or target_name in _TASK_ALIASES:
        return {
            "added": False,
            "error": "タスクへの追加はcreate_taskを使ってください。",
        }
    collection = _find_custom_list(list_id=list_id, list_name=list_name)
    if collection is None:
        return {
            "added": False,
            "error": "追加先のカスタムリストが見つかりません。",
            "list_id": list_id,
            "list_name": list_name,
        }

    cleaned_title = str(title or "").strip()
    if not cleaned_title:
        return {"added": False, "error": "項目名を指定してください。"}
    if len(cleaned_title) > 200:
        return {"added": False, "error": "項目名は200文字以内にしてください。"}

    now = db.now_iso()
    normalized_status = str(status or "active").strip() or "active"
    metadata_json = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)
    with db.get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO list_items "
            "(collection_id, title, status, note, metadata_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                collection["id"],
                cleaned_title,
                normalized_status,
                note,
                metadata_json,
                now,
                now,
            ),
        )
        item_id = int(cur.lastrowid)

    return {
        "added": True,
        "list": collection,
        "item": {
            "id": item_id,
            "title": cleaned_title,
            "status": normalized_status,
            "note": note,
            "metadata": metadata or {},
            "created_at": now,
            "updated_at": now,
        },
    }
