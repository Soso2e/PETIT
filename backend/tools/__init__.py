"""Tool implementations and registry for PETIT.

Importing this package registers all built-in tools.
"""
from . import (
    agent_actions,
    brain,
    brain_projects,
    briefing,
    context,
    current_time,
    github,
    linkraft,
    lists,
    memory,
    notion,
    notion_projects,
    notion_search,
    project_completion,
    project_registration,
    project_status,
    reminders,
    schedule,
    tasks,
    tasks_phase2,
    task_hierarchy,
    task_reads,
    task_defaults,
    work_sessions,
)  # noqa: F401  (import for side-effect registration)
from .. import web_tools  # noqa: F401  (register web/news/weather tools)
from . import registry
from .registry import dispatch, openai_tools_schema, parse_arguments, registered_names, requires_confirmation, risk_for

registry.append_description(
    "update_task",
    (
        "タスクの親子関係は変更しない。parent_idやparent_task_idを渡さず、"
        "親子変更にはset_task_parentを使う。明示的な書き込み依頼では自然文で事前確認せずToolをcallし、"
        "確認はRuntimeに一度だけ表示させる。"
    ),
)

__all__ = [
    "dispatch",
    "openai_tools_schema",
    "parse_arguments",
    "registered_names",
    "requires_confirmation",
    "risk_for",
]
