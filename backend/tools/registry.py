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

# Existing tools can keep using requires_confirmation while migration happens.
# These overrides encode the first agreed low-risk set without forcing every
# decorator to change in one release.
_DEFAULT_RISKS: dict[str, ToolRisk] = {
    "create_task": "low_risk_write",
    "add_task": "low_risk_write",
    "add_list_item": "low_risk_write",
    "create_handoff_note": "low_risk_write",
    "save_memory": "low_risk_write",
    "ignore_github_repository_candidate": "low_risk_write",
    "add_schedule": "confirm_write",
    "update_task": "confirm_write",
    "complete_task": "confirm_write",
    "edit_brain_note": "confirm_write",
    "create_list": "confirm_write",
    "link_github_repository_candidate": "confirm_write",
}


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Handler
    risk: ToolRisk = "safe_read"


_REGISTRY: dict[str, Tool] = {}


def _resolve_risk(
    name: str,
    *,
    risk: ToolRisk | None,
    requires_confirmation: bool,
) -> ToolRisk:
    if risk is not None:
        return risk
    if name in _DEFAULT_RISKS:
        return _DEFAULT_RISKS[name]
    # Backwards compatibility: every legacy confirmation-gated write remains
    # confirmation-gated unless it is explicitly migrated above.
    if requires_confirmation:
        return "confirm_write"
    return "safe_read"


def tool(
    name: str,
    description: str,
    parameters: dict[str, Any],
    *,
    requires_confirmation: bool = False,
    risk: ToolRisk | None = None,
) -> Callable[[Handler], Handler]:
    """Decorator that registers a function as a callable tool.

    ``risk`` is the preferred policy metadata. ``requires_confirmation`` stays
    supported for compatibility and maps to ``confirm_write`` by default.
    """

    def decorator(func: Handler) -> Handler:
        _REGISTRY[name] = Tool(
            name=name,
            description=description,
            parameters=parameters,
            handler=func,
            risk=_resolve_risk(
                name,
                risk=risk,
                requires_confirmation=requires_confirmation,
            ),
        )
        return func

    return decorator


def append_description(name: str, suffix: str) -> None:
    """Append guidance to one registered Tool without replacing its handler."""
    tool_obj = _REGISTRY.get(name)
    text = str(suffix or "").strip()
    if tool_obj is None or not text or text in tool_obj.description:
        return
    tool_obj.description = f"{tool_obj.description.rstrip()} {text}"


def registered_names() -> list[str]:
    return sorted(_REGISTRY.keys())


def risk_for(name: str) -> ToolRisk:
    tool_obj = _REGISTRY.get(name)
    return tool_obj.risk if tool_obj else "safe_read"


def requires_confirmation(name: str) -> bool:
    return risk_for(name) in {"confirm_write", "destructive"}


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return (
            isinstance(value, int)
            and not isinstance(value, bool)
        ) or (
            isinstance(value, str)
            and value.strip().isdigit()
        )
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def _validate_write_arguments(name: str, arguments: dict[str, Any]) -> None:
    """Reject malformed confirmation-gated writes before asking the user."""
    tool_obj = _REGISTRY.get(name)
    if tool_obj is None or tool_obj.risk not in {"confirm_write", "destructive"}:
        return

    schema = tool_obj.parameters if isinstance(tool_obj.parameters, dict) else {}
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = [str(item) for item in schema.get("required") or []]

    unknown = sorted(str(key) for key in arguments if key not in properties)
    if unknown:
        raise ValueError(f"unknown arguments for {name}: {', '.join(unknown)}")

    missing = [key for key in required if key not in arguments]
    if missing:
        raise ValueError(f"missing required arguments for {name}: {', '.join(missing)}")

    for key, value in arguments.items():
        spec = properties.get(key)
        if not isinstance(spec, dict):
            continue
        expected = spec.get("type")
        expected_types = [expected] if isinstance(expected, str) else list(expected or [])
        if expected_types and not any(_matches_type(value, item) for item in expected_types):
            rendered = "/".join(str(item) for item in expected_types)
            raise ValueError(f"invalid type for {name}.{key}: expected {rendered}")
        enum = spec.get("enum")
        if isinstance(enum, list) and value not in enum:
            raise ValueError(f"invalid value for {name}.{key}: expected one of {enum}")


def parse_arguments(name: str, arguments: dict[str, Any] | str | None) -> dict[str, Any]:
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError as exc:
            raise ValueError(f"could not parse arguments for {name}") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"arguments for {name} must be an object")
    else:
        parsed = dict(arguments or {})

    _validate_write_arguments(name, parsed)
    return parsed


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
        # The legacy handler remains the source of schedule data.  Core only
        # supplies the execution contract, policy, freshness, and audit path.
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
