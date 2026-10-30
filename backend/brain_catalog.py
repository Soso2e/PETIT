"""Small model-facing index over the existing registry, with live availability checks."""
from __future__ import annotations
from . import config, request_context, tools

DISCOVER = "discover_tools"
# A small useful first-call set, independent of utterance spelling or provider.
DIRECT = {"get_current_time", "get_tasks", "get_schedule", "get_weather", "search_news"}
DISCOVERY_SCHEMA = {"type":"function", "function": {"name":DISCOVER,
    "description":"必要なToolの詳細schemaを取得する。候補名はCapability一覧を参照。雑談では呼ばない。複数名をまとめて指定できる。操作自体は実行しない。",
    "parameters":{"type":"object", "properties":{"names":{"type":"array", "items":{"type":"string"}, "minItems":1,"maxItems":8}},
                  "required":["names"], "additionalProperties":False}}}


def available(schema: dict, *, local_only: bool, setup: dict) -> bool:
    name = schema["function"]["name"]
    if name not in tools.registered_names():
        return False
    if name in {"get_weather", "search_news"} and tools.risk_for(name) != "safe_read":
        return False
    # A local-only Thread may use internal state, never external read services.
    if local_only and name in {"get_weather", "search_news", "search_notion", "gmail_search", "gmail_get_message"}:
        return False
    if name in {"gmail_search", "gmail_get_message"}:
        return "gmail" in setup["connected"] and bool(setup["secrets"].get("google_tokens"))
    if name == "search_notion":
        return bool(config.NOTION_API_KEY)
    if name in {"get_local_development_status", "list_project_workspaces", "link_project_workspace", "unlink_project_workspace"}:
        return bool(config.WORKSPACE_CONTEXT_ENABLED and config.WORKSPACE_LOCAL_DEVELOPMENT_ENABLED)
    return True


class Catalog:
    def __init__(self):
        self.selected = set(DIRECT)

    def full(self):
        from . import brain
        return brain.schemas() if request_context.current_is_admin() else []

    def index(self) -> str:
        # Names and reviewed risk are enough to discover the complete validated schema.
        return " / ".join(x["function"]["name"] + ":" + tools.risk_for(x["function"]["name"]) for x in self.full())

    def schemas(self):
        full = self.full()
        return ([x for x in full if x["function"]["name"] in self.selected] + [DISCOVERY_SCHEMA]) if full else []

    def discover(self, raw):
        from .provider_runtime import validate_arguments
        from .conversation_store import encode
        args = validate_arguments(DISCOVERY_SCHEMA["function"]["parameters"], raw)
        catalog = {x["function"]["name"]:x for x in self.full()}
        if any(name not in catalog for name in args["names"]):
            raise ValueError("tool_unavailable_or_not_public")
        self.selected.update(args["names"])
        return encode({"schemas":[catalog[name] for name in args["names"]], "executed":False})
