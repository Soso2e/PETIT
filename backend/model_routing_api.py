"""Model routing API endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import lmstudio_client, model_routing

router = APIRouter()


class ModelRoutingUpdate(BaseModel):
    chat: str | None = None
    agent: str | None = None


@router.get("/api/model-routing")
def get_model_routing() -> dict[str, Any]:
    return model_routing.public_status()


@router.post("/api/model-routing")
def update_model_routing(payload: ModelRoutingUpdate) -> Any:
    updates = {
        route: value
        for route, value in (("chat", payload.chat), ("agent", payload.agent))
        if value is not None
    }
    try:
        result = model_routing.update_selection(updates)
    except model_routing.ModelRoutingError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    lmstudio_client.clear_health_cache()
    return result
