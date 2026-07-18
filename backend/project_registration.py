"""Confirmation-first project registration and alias management for PETIT."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from typing import Any

from . import db, project_continuity

log = logging.getLogger(__name__)

_REGISTRATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS project_write_receipts (
    idempotency_key TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

_ALIAS_PATTERNS = (
    re.compile(
        r"^[「『\"]?(?P<alias>.+?)[」』\"]?を[「『\"]?(?P<target>.+?)[」』\"]?の別名(?:にして|として追加(?:して)?|に追加(?:して)?)?[。.!！]*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^[「『\"]?(?P<target>.+?)[」』\"]?に[「『\"]?(?P<alias>.+?)[」』\"]?を?別名(?:として)?追加(?:して)?[。.!！]*$",
        re.IGNORECASE,
    ),
)
_REGISTER_PATTERN = re.compile(
    r"^[「『\"]?(?P<name>.+?)[」』\"]?を(?:新規)?プロジェクト(?:として)?登録(?:して|する)?[。.!！]*$",
    re.IGNORECASE,
)


def ensure_registration_schema() -> None:
    project_continuity.ensure_project_schema()
    with db.get_connection() as conn:
        conn.executescript(_REGISTRATION_SCHEMA)


def _clean_name(value: str) -> str:
    return value.strip(" \t\r\n、,。．.!！?？「」『』\"'")


def _idempotency_key(operation: str, user_id: str, *parts: str) -> str:
    normalized = [project_continuity.normalize_alias(part) for part in parts]
    source = "|".join([operation, user_id, *normalized])
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _receipt(key: str) -> dict[str, Any] | None:
    ensure_registration_schema()
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT result_json FROM project_write_receipts WHERE idempotency_key=?",
            (key,),
        ).fetchone()
    if not row:
        return None
    try:
        result = json.loads(str(row["result_json"]))
    except json.JSONDecodeError:
        return None
    return result if isinstance(result, dict) else None


def _save_receipt(key: str, operation: str, result: dict[str, Any]) -> None:
    ensure_registration_schema()
    with db.get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO project_write_receipts (idempotency_key, operation, result_json, created_at) VALUES (?, ?, ?, ?)",
            (key, operation, json.dumps(result, ensure_ascii=False, default=str), db.now_iso()),
        )


def preview_new_project(name: str, *, user_id: str, set_active: bool = True) -> dict[str, Any]:
    name = _clean_name(name)
    if not name:
        raise ValueError("project name is required")
    existing = project_continuity.find_projects_by_alias(name)
    if len(existing) == 1:
        project = existing[0]
        return {
            "reply": f"「{name}」は既に「{project['name']}」として登録されているよ。そこへ切り替える？",
            "used_tools": [],
            "pending_actions": [
                {
                    "name": "activate_internal_project",
                    "arguments": {
                        "user_id": user_id,
                        "project_id": project["id"],
                    },
                }
            ],
            "persist": True,
            "model_route": {
                "kind": "project_registration_existing",
                "model": None,
                "project_id": project["id"],
            },
        }
    if len(existing) > 1:
        names = "、".join(f"「{item['name']}」" for item in existing[:5])
        return {
            "reply": f"「{name}」は既存の複数プロジェクトに一致するよ。候補は{names}。新規登録せず、どれか指定して。",
            "used_tools": [],
            "persist": True,
            "model_route": {"kind": "project_registration_ambiguous", "model": None},
        }
    key = _idempotency_key("create_project", user_id, name)
    return {
        "reply": f"「{name}」はまだプロジェクト台帳にないよ。新規プロジェクトとして登録して開始する？",
        "used_tools": [],
        "pending_actions": [
            {
                "name": "create_internal_project",
                "arguments": {
                    "user_id": user_id,
                    "name": name,
                    "set_active": set_active,
                    "idempotency_key": key,
                },
            }
        ],
        "persist": True,
        "model_route": {"kind": "project_registration_preview", "model": None, "name": name},
    }


def _alias_preview(alias: str, target: str, *, user_id: str) -> dict[str, Any]:
    alias = _clean_name(alias)
    target = _clean_name(target)
    if not alias or not target:
        raise ValueError("alias and target are required")
    targets = project_continuity.find_projects_by_alias(target)
    if not targets:
        return {
            "reply": f"別名の追加先「{target}」が見つからない。先に正式なプロジェクト名を確認したい。",
            "used_tools": [],
            "persist": True,
            "model_route": {"kind": "project_alias_target_missing", "model": None},
        }
    if len(targets) > 1:
        names = "、".join(f"「{item['name']}」" for item in targets[:5])
        return {
            "reply": f"追加先の「{target}」が複数あるよ。候補は{names}。正式名をもう少し具体的にして。",
            "used_tools": [],
            "persist": True,
            "model_route": {"kind": "project_alias_target_ambiguous", "model": None},
        }
    project = targets[0]
    collisions = [
        item for item in project_continuity.find_projects_by_alias(alias)
        if item["id"] != project["id"]
    ]
    warning = ""
    if collisions:
        names = "、".join(f"「{item['name']}」" for item in collisions[:5])
        warning = f" ただし、この呼び名は既に{names}でも使われていて、今後は候補確認が必要になる。"
    key = _idempotency_key("add_alias", user_id, project["id"], alias)
    return {
        "reply": f"「{project['name']}」へ「{alias}」を別名として追加するよ。{warning}この内容で実行する？",
        "used_tools": [],
        "pending_actions": [
            {
                "name": "add_internal_project_alias",
                "arguments": {
                    "user_id": user_id,
                    "project_id": project["id"],
                    "alias": alias,
                    "idempotency_key": key,
                },
            }
        ],
        "persist": True,
        "model_route": {
            "kind": "project_alias_preview",
            "model": None,
            "project_id": project["id"],
            "alias_collisions": len(collisions),
        },
    }


def try_handle_registration_turn(user_message: str, *, user_id: str) -> dict[str, Any] | None:
    """Create deterministic registration previews; never write directly."""
    try:
        text = " ".join(user_message.strip().split())
        for pattern in _ALIAS_PATTERNS:
            match = pattern.fullmatch(text)
            if match:
                return _alias_preview(match.group("alias"), match.group("target"), user_id=user_id)
        match = _REGISTER_PATTERN.fullmatch(text)
        if match:
            return preview_new_project(match.group("name"), user_id=user_id)
        return None
    except Exception as exc:  # noqa: BLE001
        log.debug("project registration routing skipped: %s", exc)
        return None


def create_internal_project(
    *,
    user_id: str,
    name: str,
    set_active: bool,
    idempotency_key: str,
) -> dict[str, Any]:
    ensure_registration_schema()
    replay = _receipt(idempotency_key)
    if replay:
        return replay | {"idempotency_hit": True}
    name = _clean_name(name)
    expected = _idempotency_key("create_project", user_id, name)
    if idempotency_key != expected:
        raise ValueError("invalid project registration idempotency key")
    existing = project_continuity.find_projects_by_alias(name)
    if len(existing) > 1:
        raise ValueError("project name is ambiguous")
    if existing:
        project = project_continuity.get_project(str(existing[0]["id"])) or existing[0]
        created = False
    else:
        project_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"petit:{idempotency_key}"))
        project = project_continuity.get_project(project_id) or project_continuity.create_project(
            name,
            project_id=project_id,
        )
        created = True
    active = project_continuity.set_active_project(user_id, str(project["id"])) if set_active else None
    result = {
        "created": created,
        "project": project,
        "active_project": active,
        "idempotency_hit": False,
    }
    _save_receipt(idempotency_key, "create_project", result)
    return result


def add_internal_project_alias(
    *,
    user_id: str,
    project_id: str,
    alias: str,
    idempotency_key: str,
) -> dict[str, Any]:
    ensure_registration_schema()
    replay = _receipt(idempotency_key)
    if replay:
        return replay | {"idempotency_hit": True}
    project = project_continuity.get_project(project_id)
    if not project:
        raise ValueError("project not found")
    alias = _clean_name(alias)
    expected = _idempotency_key("add_alias", user_id, project_id, alias)
    if idempotency_key != expected:
        raise ValueError("invalid project alias idempotency key")
    added = project_continuity.add_project_alias(project_id, alias)
    collisions = [
        item for item in project_continuity.find_projects_by_alias(alias)
        if item["id"] != project_id
    ]
    result = {
        "added": added,
        "project": project,
        "alias": alias,
        "collision_project_ids": [item["id"] for item in collisions],
        "idempotency_hit": False,
    }
    _save_receipt(idempotency_key, "add_alias", result)
    return result


def activate_internal_project(*, user_id: str, project_id: str) -> dict[str, Any]:
    project = project_continuity.get_project(project_id)
    if not project:
        raise ValueError("project not found")
    active = project_continuity.set_active_project(user_id, project_id)
    return {"activated": True, "project": project, "active_project": active}
