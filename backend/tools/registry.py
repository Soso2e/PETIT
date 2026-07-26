"""A tiny tool registry.

Register a tool with the @tool decorator. Each tool declares an OpenAI-style
JSON-schema for its parameters and a handler that takes keyword arguments and
returns a JSON-serialisable result.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Literal

from .. import config

Handler = Callable[..., Any]
ToolRisk = Literal["safe_read", "low_risk_write", "confirm_write", "destructive"]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Handler
    risk: ToolRisk = "safe_read"


_REGISTRY: dict[str, Tool] = {}


def tool(
    name: str,
    description: str,
    parameters: dict[str, Any],
    *,
    risk: ToolRisk | None = None,
    requires_confirmation: bool = False,
) -> Callable[[Handler], Handler]:
    """Decorator that registers a function as a callable tool.

    ``requires_confirmation=True`` remains supported for compatibility and maps
    to ``confirm_write`` unless an explicit ``risk`` is supplied.
    """

    resolved_risk: ToolRisk = risk or ("confirm_write" if requires_confirmation else "safe_read")

    def decorator(func: Handler) -> Handler:
        _REGISTRY[name] = Tool(
            name=name,
            description=description,
            parameters=parameters,
            handler=func,
            risk=resolved_risk,
        )
        return func

    return decorator


def registered_names() -> list[str]:
    return sorted(_REGISTRY.keys())


def tool_risk(name: str) -> ToolRisk:
    tool_obj = _REGISTRY.get(name)
    return tool_obj.risk if tool_obj else "safe_read"


def requires_confirmation(name: str) -> bool:
    return tool_risk(name) in {"confirm_write", "destructive"}


def parse_arguments(name: str, arguments: dict[str, Any] | str | None) -> dict[str, Any]:
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError as exc:
            raise ValueError(f"could not parse arguments for {name}") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"arguments for {name} must be an object")
        return parsed
    return dict(arguments or {})


def openai_tools_schema() -> list[dict[str, Any]]:
    """Return the tool list in the format the chat completions API expects."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in _REGISTRY.values()
    ]


def dispatch(name: str, arguments: dict[str, Any] | str | None) -> str:
    """Execute a tool by name and return a string result for the LLM.

    Arguments may arrive as a JSON string (as tool calls do) or a dict.
    Errors are returned as text rather than raised, so the agent loop can
    feed them back to the model.
    """
    tool_obj = _REGISTRY.get(name)
    if tool_obj is None:
        return f"[error] unknown tool: {name}"

    try:
        arguments = parse_arguments(name, arguments)
    except ValueError as exc:
        return f"[error] {exc}"

    if name == "get_schedule" and config.USE_SONA_CORE:
        try:
            from .. import sona_core_schedule
        except ImportError:
            return "[error] Sona Agent Core is unavailable; PETIT_USE_SONA_CORE cannot use the legacy path"
        return sona_core_schedule.dispatch_get_schedule(arguments)

    try:
        result = tool_obj.handler(**arguments)
    except TypeError as exc:
        return f"[error] bad arguments for {name}: {exc}"
    except Exception as exc:  # noqa: BLE001 - surface tool errors to the model
        return f"[error] {name} failed: {exc}"

    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False, default=str)
