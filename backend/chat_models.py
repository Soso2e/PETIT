"""Shared API models for chat and confirmation flows."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PendingAction(BaseModel):
    approval_id: str
    name: str
    arguments: dict[str, Any]


class ChatResponse(BaseModel):
    reply: str
    used_tools: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    model_route: dict[str, Any] | None = None
    request_id: str | None = None
    pending_actions: list[PendingAction] = Field(default_factory=list)


class ActionDecision(BaseModel):
    approved: bool
