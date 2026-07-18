"""Confirmed write tools for PETIT's internal project registry."""
from __future__ import annotations

from .. import project_registration
from .registry import tool


@tool(
    name="create_internal_project",
    description="確認済みの名称でPETIT内部プロジェクトを作成し、必要なら現在プロジェクトへ切り替える。",
    parameters={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "name": {"type": "string"},
            "set_active": {"type": "boolean"},
            "idempotency_key": {"type": "string"},
        },
        "required": ["user_id", "name", "set_active", "idempotency_key"],
        "additionalProperties": False,
    },
    requires_confirmation=True,
)
def create_internal_project(**kwargs):
    return project_registration.create_internal_project(**kwargs)


@tool(
    name="add_internal_project_alias",
    description="確認済みの呼び名を既存PETIT内部プロジェクトの別名として追加する。",
    parameters={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "project_id": {"type": "string"},
            "alias": {"type": "string"},
            "idempotency_key": {"type": "string"},
        },
        "required": ["user_id", "project_id", "alias", "idempotency_key"],
        "additionalProperties": False,
    },
    requires_confirmation=True,
)
def add_internal_project_alias(**kwargs):
    return project_registration.add_internal_project_alias(**kwargs)


@tool(
    name="activate_internal_project",
    description="確認済みの既存PETIT内部プロジェクトへ現在作業を切り替える。",
    parameters={
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "project_id": {"type": "string"},
        },
        "required": ["user_id", "project_id"],
        "additionalProperties": False,
    },
    requires_confirmation=True,
)
def activate_internal_project(**kwargs):
    return project_registration.activate_internal_project(**kwargs)
