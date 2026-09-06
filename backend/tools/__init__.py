"""PETIT tool registry public API.

Built-in tool implementations are registered explicitly by application
composition via ``backend.tools.builtins.register_builtin_tools``.
"""
from .builtins import builtin_module_names, register_builtin_tools
from .registry import dispatch, openai_tools_schema, parse_arguments, registered_names, requires_confirmation, risk_for

__all__ = [
    "builtin_module_names",
    "dispatch",
    "openai_tools_schema",
    "parse_arguments",
    "register_builtin_tools",
    "registered_names",
    "requires_confirmation",
    "risk_for",
]
