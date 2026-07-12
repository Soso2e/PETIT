"""Briefing tools."""
from __future__ import annotations

from typing import Any

from .. import briefing
from .registry import tool


@tool(
    name="create_daily_briefing",
    description=(
        "指定日の予定・タスク・最近の流れから、朝ブリーフィングと今やる1個を作る。"
        "「おはよう」「今日何すればいい？」「今日の最初の一手は？」のような発話で使う。"
        "date は YYYY-MM-DD。省略時は今日。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "date": {"type": "string", "description": "対象日 YYYY-MM-DD。省略可。"},
        },
    },
)
def create_daily_briefing(date: str | None = None) -> dict[str, Any]:
    return briefing.create_daily_briefing(date)
