"""FastAPI application composition root.

Run with:  uvicorn backend.main:app --reload
or:        python -m backend.main
"""
from __future__ import annotations

from fastapi import FastAPI

from . import chat, config, frontend_api, health, lifecycle, model_routing_api, notion_webhook, notifications, pending_actions, shortcut_voice, support_api, voice, work_sessions

app = FastAPI(title="PETIT", description="Personal AI Assistant (MVP)")
app.include_router(health.router)
app.include_router(model_routing_api.router)
app.include_router(notion_webhook.router)
app.include_router(notifications.router)
app.include_router(pending_actions.router)
app.include_router(work_sessions.router)
app.include_router(chat.router)
app.include_router(shortcut_voice.router)
app.include_router(voice.router)
app.include_router(support_api.router)
lifecycle.register(app)
frontend_api.register(app)


def main() -> None:
    import uvicorn

    uvicorn.run("backend.main:app", host=config.HOST, port=config.PORT, reload=False)


if __name__ == "__main__":
    main()
