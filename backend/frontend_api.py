"""Static frontend registration for PETIT's FastAPI app."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config

router = APIRouter()


@router.get("/service-worker.js", include_in_schema=False)
@router.get("/sw.js", include_in_schema=False)
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


@router.get("/apple-touch-icon.png", include_in_schema=False)
@router.get("/apple-touch-icon-precomposed.png", include_in_schema=False)
def apple_touch_icon() -> Any:
    """Serve the Apple touch icon from the root path for mobile Safari."""
    icon_file = config.FRONTEND_DIR / "apple-touch-icon.png"
    if icon_file.exists():
        return FileResponse(icon_file, media_type="image/png")
    return JSONResponse({"detail": "apple touch icon not found"}, status_code=404)


@router.get("/")
def index() -> Any:
    index_file = config.FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return JSONResponse({"detail": "frontend not built"}, status_code=404)


def register(app: FastAPI) -> None:
    """Mount static assets and register frontend routes when the frontend exists."""
    if not config.FRONTEND_DIR.exists():
        return
    app.mount("/static", StaticFiles(directory=config.FRONTEND_DIR), name="static")
    app.include_router(router)
