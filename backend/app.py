"""PETIT FastAPI application composition."""
from __future__ import annotations

from fastapi import FastAPI

from . import (
    chat,
    frontend_api,
    health,
    lifecycle,
    model_routing_api,
    notion_webhook,
    notifications,
    pending_actions,
    shortcut_voice,
    support_api,
    tools,
    voice,
    work_sessions,
    workspace_context,
)
from .kernel.modules import ModuleDefinition, ModuleRegistry


def build_modules() -> tuple[ModuleDefinition, ...]:
    """Return PETIT's explicit application module set."""
    return (
        ModuleDefinition(id="builtin-tools", registrars=(tools.register_builtin_tools,)),
        ModuleDefinition(id="health", routers=(health.router,)),
        ModuleDefinition(id="model-routing", routers=(model_routing_api.router,)),
        ModuleDefinition(id="notion-webhook", routers=(notion_webhook.router,)),
        ModuleDefinition(id="notifications", routers=(notifications.router,)),
        ModuleDefinition(
            id="pending-actions",
            routers=(pending_actions.router,),
            dependencies=("builtin-tools",),
        ),
        ModuleDefinition(id="work-sessions", routers=(work_sessions.router,)),
        ModuleDefinition(id="workspace-context", routers=(workspace_context.router,), registrars=(workspace_context.register,)),
        ModuleDefinition(
            id="chat",
            routers=(chat.router,),
            dependencies=("builtin-tools", "pending-actions"),
        ),
        ModuleDefinition(id="shortcut-voice", routers=(shortcut_voice.router,), dependencies=("chat",)),
        ModuleDefinition(id="voice", routers=(voice.router,)),
        ModuleDefinition(id="support-api", routers=(support_api.router,)),
        ModuleDefinition(id="lifecycle", registrars=(lifecycle.register,)),
        ModuleDefinition(id="frontend", registrars=(frontend_api.register,)),
    )


def create_app() -> FastAPI:
    app = FastAPI(title="PETIT", description="Personal AI Assistant (MVP)")
    ModuleRegistry(build_modules()).register(app)
    return app
