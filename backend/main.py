"""FastAPI application composition root + static frontend.

Run with:  uvicorn backend.main:app --reload
or:        python -m backend.main
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import chat, config, health, lifecycle, model_routing_api, notion_webhook, notifications, pending_actions, shortcut_voice, support_api, voice, work_sessions

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


# --- Static frontend ---------------------------------------------------------
# Mount assets under /static and serve index.html at the root.
if config.FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=config.FRONTEND_DIR), name="static")

    @app.get("/service-worker.js", include_in_schema=False)
    @app.get("/sw.js", include_in_schema=False)
    def service_worker() -> Any:
        service_worker_file = config.FRONTEND_DIR / "service-worker.js"
        if service_worker_file.exists():
            return FileResponse(
                service_worker_file,
                media_type="application/javascript",
                headers={
                    "Cache-Control": "no-cache",
                    "Service-Worker-Allowed": "/",
                },
            )
        return JSONResponse({"detail": "service worker not found"}, status_code=404)

    @app.get("/")
    def index() -> Any:
        index_file = config.FRONTEND_DIR / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return JSONResponse({"detail": "frontend not built"}, status_code=404)


def main() -> None:
    import uvicorn

    uvicorn.run("backend.main:app", host=config.HOST, port=config.PORT, reload=False)


if __name__ == "__main__":
    main()
