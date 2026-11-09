"""Conversation Tools for handing multi-step work to a CLI (#411)."""
from __future__ import annotations

from .registry import tool
from .. import delegations, request_context


@tool(
    name="delegate_to_agent",
    description=(
        "複数ステップの作業をCLIエージェントに任せ、裏で動かす。すぐ受付結果を返すので、利用者は会話を続けられる。"
        "対象はPETIT Homeのファイル作業、PETIT Toolを組み合わせた作業、メール本文の確認。"
        "開発・リポジトリ調査・PCファイル作業には propose_development_job を使う。Web調査や単純な定型操作には使わない。"
        "1回の依頼につき1件まで。使うCLIはCoreが決める。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "goal": {"type": "string", "minLength": 1, "maxLength": 2000, "description": "何を達成してほしいか"},
            "context_summary": {"type": "string", "maxLength": 4000, "description": "作業に必要な会話の文脈。依頼の原文はCoreが別に渡す"},
        },
        "required": ["goal"],
        "additionalProperties": False,
    },
    risk="low_risk_write",
)
def delegate_to_agent(goal: str, context_summary: str = ""):
    return delegations.start(goal, context_summary)


@tool(
    name="get_delegation_status",
    description="任せた作業の状態・確認待ち・報告を確認する。IDを省くとこの会話の直近の作業を返す。",
    parameters={
        "type": "object",
        "properties": {"delegation_id": {"type": "string", "maxLength": 64}},
        "additionalProperties": False,
    },
    risk="safe_read",
)
def get_delegation_status(delegation_id: str | None = None):
    if not request_context.current_is_admin():
        raise ValueError("administrator_required")
    if delegation_id:
        return delegations.get(delegation_id)
    _, thread_id = request_context.current_ids()
    return {"delegations": delegations.listing(thread_id or "")}


@tool(
    name="cancel_delegation",
    description="任せた作業を止める。すでに行われた変更は元に戻さない。",
    parameters={
        "type": "object",
        "properties": {"delegation_id": {"type": "string", "maxLength": 64}},
        "required": ["delegation_id"],
        "additionalProperties": False,
    },
    risk="low_risk_write",
)
def cancel_delegation(delegation_id: str):
    if not request_context.current_is_admin():
        raise ValueError("administrator_required")
    return delegations.cancel(delegation_id)
