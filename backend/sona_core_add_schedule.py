"""Milestone 3 safe-write adapter for PETIT's existing ``add_schedule``."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from sona_agent_core import (
    ApprovalDecision, CoreError, JsonLinesAuditSink, SQLiteApprovalStore, ToolCall,
    ToolDefinition, ToolExecutor, ToolInvocation, ToolResult,
)
from sona_agent_core.runtime import InMemoryToolRegistry

from . import config
from .sona_core_schedule import PetitSchedulePolicyEngine, build_context
from .tools import schedule

ScheduleWriter = Callable[..., dict[str, Any]]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PetitAddScheduleAdapter:
    """Wrap the established PETIT writer without owning schedule storage."""

    definition = ToolDefinition(
        name="add_schedule",
        description="PETITのローカル予定へ、確認後に予定を1件追加する。",
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"}, "start_time": {"type": "string"},
                "end_time": {"type": "string"}, "location": {"type": "string"},
                "description": {"type": "string"}, "destination": {"type": "string", "const": "local"},
            },
            "required": ["title", "start_time"],
        },
        output_schema={"type": "object"}, version="1", risks=("write",),
        confirmation_mode="always", required_capabilities=("schedule.write",),
        supported_scopes=("personal",), idempotent=True,
        metadata={"destination": "local", "execution_path": "sona_core"},
    )

    def __init__(self, legacy_add_schedule: ScheduleWriter = schedule.add_schedule) -> None:
        self._legacy_add_schedule = legacy_add_schedule

    async def invoke(self, invocation: ToolInvocation) -> ToolResult:
        started_at = _now()
        arguments = dict(invocation.call.arguments)
        if arguments.get("destination", "local") != "local":
            return self._failed(invocation, "DESTINATION_NOT_SUPPORTED", "destination must be local", started_at)
        arguments.setdefault("destination", "local")
        try:
            data = self._legacy_add_schedule(**arguments)
        except Exception as exc:  # noqa: BLE001
            return self._failed(invocation, "SCHEDULE_WRITE_FAILED", str(exc), started_at)
        if not isinstance(data, dict) or not data.get("added"):
            message = str(data.get("error") if isinstance(data, dict) else "schedule write failed")
            return ToolResult(
                tool_call_id=invocation.call.tool_call_id, tool_name=invocation.call.name, status="failed",
                data=data, error=CoreError(code="SCHEDULE_WRITE_FAILED", message=message, category="source"),
                before=None, after=data, started_at=started_at, completed_at=_now(),
                metadata=self._metadata(invocation, data),
            )
        return ToolResult(
            tool_call_id=invocation.call.tool_call_id, tool_name=invocation.call.name, status="success",
            data=data, before=None, after=data, started_at=started_at, completed_at=_now(),
            metadata=self._metadata(invocation, data),
        )

    def _failed(self, invocation: ToolInvocation, code: str, message: str, started_at: str) -> ToolResult:
        return ToolResult(
            tool_call_id=invocation.call.tool_call_id, tool_name=invocation.call.name, status="failed",
            error=CoreError(code=code, message=message, category="validation"),
            started_at=started_at, completed_at=_now(), metadata=self._metadata(invocation, None),
        )

    @staticmethod
    def _metadata(invocation: ToolInvocation, data: dict[str, Any] | None) -> dict[str, object]:
        return {
            "execution_path": "sona_core", "core_path": True, "feature_flag": True,
            "destination": "local", "created_schedule_id": data.get("id") if data else None,
            "result": data,
        }


def _executor(adapter: PetitAddScheduleAdapter | None = None, audit_sink=None) -> ToolExecutor:
    registry = InMemoryToolRegistry()
    registry.register(adapter or PetitAddScheduleAdapter())
    return ToolExecutor(
        registry, policy_engine=PetitSchedulePolicyEngine(),
        approval_store=SQLiteApprovalStore(config.DB_PATH),
        audit_sink=audit_sink or JsonLinesAuditSink(config.SONA_CORE_AUDIT_PATH),
        approval_ttl_seconds=config.SONA_CORE_APPROVAL_TTL_SECONDS,
    )


async def create_approval(
    arguments: dict[str, Any], *, context=None, adapter: PetitAddScheduleAdapter | None = None,
    audit_sink=None, approval_id: str | None = None, idempotency_key: str | None = None,
) -> tuple[str, ToolResult]:
    approval_id = approval_id or f"petit-approval-{uuid4()}"
    invocation = ToolInvocation(
        context=context or build_context(capabilities=("schedule.write",)),
        call=ToolCall(tool_call_id=f"petit-add-schedule-{uuid4()}", name="add_schedule", arguments=dict(arguments)),
        idempotency_key=idempotency_key or f"petit-add-schedule-{uuid4()}", requested_at=_now(), approval_id=approval_id,
    )
    result = await _executor(adapter, audit_sink).execute(invocation)
    return approval_id, result


async def decide(approval_id: str, approved: bool, *, adapter: PetitAddScheduleAdapter | None = None, audit_sink=None) -> ToolResult | None:
    executor = _executor(adapter, audit_sink)
    store = executor.approval_store
    request = await store.get(approval_id)
    if request is None:
        raise KeyError(approval_id)
    decision = ApprovalDecision(
        approval_id=approval_id, approver=request.context.actor, approved=approved, decided_at=_now(),
    )
    await executor.decide_approval(decision)
    if not approved:
        return None
    return await executor.execute_approved(approval_id)


def register_pending(arguments: dict[str, Any]) -> str:
    approval_id, result = asyncio.run(create_approval(arguments))
    if result.status != "pending_approval":
        message = result.error.message if result.error else result.message or "approval request failed"
        raise RuntimeError(message)
    return approval_id


def get_pending(approval_id: str):
    return asyncio.run(SQLiteApprovalStore(config.DB_PATH).get(approval_id))


def decide_pending(approval_id: str, approved: bool) -> ToolResult | None:
    return asyncio.run(decide(approval_id, approved))
