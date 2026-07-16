"""PETIT adapter for the Sona Agent Core ``get_schedule`` vertical slice."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from sona_agent_core import (
    Actor,
    Client,
    CoreError,
    DefaultPolicyEngine,
    ExecutionContext,
    Freshness,
    JsonLinesAuditSink,
    MemoryAuditSink,
    Principal,
    ScopeRef,
    ScopeSet,
    SourceReference,
    ToolCall,
    ToolDefinition,
    ToolExecutor,
    ToolInvocation,
    ToolResult,
)
from sona_agent_core.runtime import InMemoryToolRegistry

from . import config
from .tools import schedule

ScheduleReader = Callable[..., dict[str, Any]]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_context(*, request_id: str | None = None, capabilities: tuple[str, ...] = ("schedule.read",), scope_id: str | None = None) -> ExecutionContext:
    """Create PETIT's authenticated personal context for read-only schedules."""
    principal = Principal(
        principal_id=config.PETIT_OWNER_ID,
        principal_type="user",
        provider="petit",
        capabilities=capabilities,
    )
    return ExecutionContext(
        request_id=request_id or f"petit-request-{uuid4()}",
        execution_id=f"petit-execution-{uuid4()}",
        actor=Actor(
            actor_id=config.PETIT_OWNER_ID,
            actor_type="user",
            display_name="PETIT user",
            principal=principal,
        ),
        client=Client(client_id="petit", name="PETIT", version="m2"),
        scopes=ScopeSet(primary=ScopeRef(type="personal", id=scope_id or config.PETIT_PERSONAL_SCOPE_ID, provider="petit")),
        channel="petit_web",
        metadata={"feature_flag": "PETIT_USE_SONA_CORE", "execution_path": "sona_core"},
    )


class PetitGetScheduleAdapter:
    """Expose PETIT's established schedule reader through the Core contract."""

    definition = ToolDefinition(
        name="get_schedule",
        description="PETITの指定日の予定を読み取り専用で取得する。",
        input_schema={
            "type": "object",
            "properties": {"date": {"type": "string", "description": "対象日 YYYY-MM-DD。省略可。"}},
        },
        output_schema={"type": "object"},
        version="1",
        risks=(),
        confirmation_mode="never",
        required_capabilities=("schedule.read",),
        supported_scopes=("personal",),
        idempotent=True,
    )

    def __init__(self, legacy_get_schedule: ScheduleReader = schedule.get_schedule) -> None:
        self._legacy_get_schedule = legacy_get_schedule

    async def invoke(self, invocation: ToolInvocation) -> ToolResult:
        started_at = _now()
        try:
            date_value = invocation.call.arguments.get("date")
            if date_value is not None and not isinstance(date_value, str):
                raise ValueError("date must be a string")
            data = self._legacy_get_schedule(date=date_value)
        except Exception as exc:  # noqa: BLE001 - convert adapter failures to a Core result
            return ToolResult(
                tool_call_id=invocation.call.tool_call_id,
                tool_name=invocation.call.name,
                status="failed",
                error=CoreError(code="SCHEDULE_READ_FAILED", message=str(exc), category="source"),
                started_at=started_at,
                completed_at=_now(),
            )

        freshness = _freshness(data.get("calendar_sync", {}))
        sources = _sources(data, invocation.context.scopes.primary)
        return ToolResult(
            tool_call_id=invocation.call.tool_call_id,
            tool_name=invocation.call.name,
            status="success",
            data=data,
            sources=sources,
            freshness=freshness,
            started_at=started_at,
            completed_at=_now(),
            metadata={
                "feature_flag": "PETIT_USE_SONA_CORE",
                "execution_path": "sona_core",
                "source_providers": tuple(source.provider for source in sources),
                "freshness_status": freshness.status,
            },
        )


class PetitSchedulePolicyEngine(DefaultPolicyEngine):
    """Enforce the adapter's declared primary-scope boundary."""

    async def evaluate_tool(self, context: ExecutionContext, definition: ToolDefinition, call: ToolCall):
        if definition.supported_scopes and context.scopes.primary.type not in definition.supported_scopes:
            from sona_agent_core.runtime.policy import PolicyDecision

            return PolicyDecision(
                effect="deny",
                reason_code="SCOPE_NOT_SUPPORTED",
                message="primary scope is not supported by this tool",
                metadata={"supported_scopes": definition.supported_scopes},
            )
        return await super().evaluate_tool(context, definition, call)


class PetitScheduleToolExecutor(ToolExecutor):
    """Copy result provenance and freshness into the durable audit event."""

    async def _emit_audit(self, context, status, invocation, **kwargs):
        result = kwargs.get("result")
        metadata = dict(kwargs.get("metadata") or {})
        if result is not None:
            freshness = result.freshness
            sync = result.data.get("calendar_sync", {}) if isinstance(result.data, dict) else {}
            metadata.update(
                {
                    "sources": [
                        {
                            "provider": source.provider,
                            "resource_type": source.resource_type,
                            "external_id": source.external_id,
                        }
                        for source in result.sources
                    ],
                    "freshness": (
                        {
                            "status": freshness.status,
                            "source_updated_at": freshness.source_updated_at,
                            "observed_at": freshness.observed_at,
                        }
                        if freshness is not None
                        else None
                    ),
                    "stale": bool(freshness and freshness.status == "stale"),
                    "last_synced_at": sync.get("last_synced_at"),
                    "sync_error": sync.get("error"),
                }
            )
        kwargs["metadata"] = metadata
        await super()._emit_audit(context, status, invocation, **kwargs)


def _freshness(sync: dict[str, Any]) -> Freshness:
    if sync.get("stale"):
        status = "stale"
    elif sync.get("ok"):
        status = "fresh"
    else:
        status = "unknown"
    return Freshness(
        status=status,
        observed_at=_now(),
        source_updated_at=sync.get("last_synced_at"),
        max_age_seconds=int(config.CALENDAR_SYNC_TTL_SECONDS),
    )


def _sources(data: dict[str, Any], scope: ScopeRef) -> tuple[SourceReference, ...]:
    sync = data.get("calendar_sync", {})
    seen: set[str] = set()
    references: list[SourceReference] = []
    for event in data.get("events", []):
        provider = str(event.get("source") or "calendar_cache")
        if provider in seen:
            continue
        seen.add(provider)
        references.append(
            SourceReference(
                provider=provider,
                resource_type="calendar_events_cache",
                external_id=provider,
                title="PETIT calendar cache",
                scope=scope,
                retrieved_at=sync.get("last_synced_at"),
                metadata={"stale": bool(sync.get("stale")), "sync_error": sync.get("error")},
            )
        )
    return tuple(references)


async def execute_get_schedule(
    arguments: dict[str, Any],
    *,
    context: ExecutionContext | None = None,
    audit_sink: MemoryAuditSink | JsonLinesAuditSink | None = None,
    adapter: PetitGetScheduleAdapter | None = None,
) -> ToolResult:
    registry = InMemoryToolRegistry()
    registry.register(adapter or PetitGetScheduleAdapter())
    executor = PetitScheduleToolExecutor(
        registry,
        policy_engine=PetitSchedulePolicyEngine(),
        audit_sink=audit_sink or JsonLinesAuditSink(config.SONA_CORE_AUDIT_PATH),
    )
    now = _now()
    invocation = ToolInvocation(
        context=context or build_context(),
        call=ToolCall(tool_call_id=f"petit-schedule-{uuid4()}", name="get_schedule", arguments=arguments),
        idempotency_key=f"petit-schedule-{uuid4()}",
        requested_at=now,
    )
    return await executor.execute(invocation)


def dispatch_get_schedule(arguments: dict[str, Any]) -> str:
    """Keep PETIT's existing string dispatch interface while using Core."""
    try:
        result = asyncio.run(execute_get_schedule(arguments))
    except ImportError:
        return "[error] Sona Agent Core is unavailable; PETIT_USE_SONA_CORE cannot use the legacy path"
    if result.status != "success":
        message = result.error.message if result.error else result.message or "schedule read failed"
        return f"[error] {message}"
    import json

    return json.dumps(result.data, ensure_ascii=False, default=str)
