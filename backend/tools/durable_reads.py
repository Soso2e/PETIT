"""Conversation bridge for durable public-news and weather lookups."""
from __future__ import annotations

from .registry import tool
from .. import durable_reads, request_context


@tool(
    name="delegate_background_research",
    description=(
        "利用者が明示的に後で調べるよう頼んだニュース・天気の公開情報検索を"
        "永続バックグラウンドJobとして受け付ける。Job IDを返し、その後も"
        "通常会話を続けられる。メール、私有ファイル、コード実行、一般Web調査は未対応。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["news", "weather"]},
            "query": {"type": "string", "maxLength": 2000},
        },
        "required": ["kind", "query"],
        "additionalProperties": False,
    },
    risk="low_risk_write",
)
def delegate_background_research(kind: str, query: str):
    if not request_context.current_is_admin():
        raise ValueError("administrator_required")
    if request_context.local_only():
        raise ValueError("local_only_external_research_forbidden")
    request_id, thread_id = request_context.current_ids()
    if not request_id or not thread_id:
        raise ValueError("active_thread_and_request_required")
    return durable_reads.enqueue(
        thread_id=thread_id, request_id=request_id, kind=kind, query=query
    )


@tool(
    name="get_background_research_status",
    description="既に受付済みのニュース・天気のバックグラウンドJobの状態と完了結果を照会する。",
    parameters={
        "type": "object",
        "properties": {"job_id": {"type": "integer"}},
        "required": ["job_id"],
        "additionalProperties": False,
    },
    risk="safe_read",
)
def get_background_research_status(job_id: int):
    if not request_context.current_is_admin():
        raise ValueError("administrator_required")
    if request_context.local_only():
        raise ValueError("local_only_external_research_forbidden")
    return durable_reads.get(int(job_id))
