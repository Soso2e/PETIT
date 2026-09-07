"""PETIT tool registry public API.

Built-in tool implementations are registered explicitly by application
composition via ``backend.tools.builtins.register_builtin_tools``.

For standalone callers (tests, scripts, diagnostics), public operations lazily
bootstrap the complete built-in catalog on first real use. Importing
``backend.tools`` itself keeps zero registration side effects, so application
composition remains explicit.
"""
from .builtins import builtin_module_names, register_builtin_tools
from . import registry as _registry


def _ensure_builtin_tools() -> None:
    # Some standalone callers import one implementation module before touching
    # this public API, leaving the registry non-empty but incomplete. The
    # centralized registrar is idempotent under Python's module cache, so always
    # apply the full catalog on real use instead of checking only for emptiness.
    register_builtin_tools()


def dispatch(name, arguments):
    _ensure_builtin_tools()
    return _registry.dispatch(name, arguments)


def openai_tools_schema():
    _ensure_builtin_tools()
    return _registry.openai_tools_schema()


def parse_arguments(name, arguments):
    _ensure_builtin_tools()
    return _registry.parse_arguments(name, arguments)


def requires_confirmation(name):
    _ensure_builtin_tools()
    return _registry.requires_confirmation(name)


def risk_for(name):
    _ensure_builtin_tools()
    return _registry.risk_for(name)


def registered_names():
    """Return currently registered names without causing registration."""
    return _registry.registered_names()


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
