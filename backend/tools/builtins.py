"""Explicit registration of PETIT built-in tools.

Importing ``backend.tools`` no longer pulls every tool implementation in by
side effect. Application composition calls ``register_builtin_tools`` through
the Module Registry before tool-consuming modules are exposed to requests.
"""
from __future__ import annotations

from importlib import import_module

from . import registry

_BUILTIN_MODULES = (
    "backend.tools.agent_actions",
    "backend.tools.brain",
    "backend.tools.brain_projects",
    "backend.tools.briefing",
    "backend.tools.context",
    "backend.tools.current_time",
    "backend.tools.github",
    "backend.tools.linkraft",
    "backend.tools.lists",
    "backend.tools.memory",
    "backend.tools.notion",
    "backend.tools.notion_projects",
    "backend.tools.notion_search",
    "backend.tools.project_completion",
    "backend.tools.project_registration",
    "backend.tools.project_status",
    "backend.tools.reminders",
    "backend.tools.schedule",
    "backend.tools.tasks",
    "backend.tools.tasks_phase2",
    "backend.tools.task_hierarchy",
    "backend.tools.task_reads",
    "backend.tools.task_defaults",
    "backend.tools.work_sessions",
    "backend.web_tools",
)


def register_builtin_tools(_app: object | None = None) -> None:
    """Import the declared built-in tool modules and apply shared guidance.

    Importing is intentionally centralized here. Python's module cache makes
    repeated registration calls safe for normal ``create_app`` usage while
    preserving the existing decorator-based tool definitions.
    """
    for module_name in _BUILTIN_MODULES:
        import_module(module_name)

    registry.append_description(
        "update_task",
        (
            "タスクの親子関係は変更しない。parent_idやparent_task_idを渡さず、"
            "親子変更にはset_task_parentを使う。明示的な書き込み依頼では自然文で事前確認せずToolをcallし、"
            "確認はRuntimeに一度だけ表示させる。"
        ),
    )


def builtin_module_names() -> tuple[str, ...]:
    """Expose the explicit catalog for tests and diagnostics."""
    return _BUILTIN_MODULES
