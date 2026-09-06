"""Notion webhook API routes."""
from __future__ import annotations

import hmac
import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from . import config, notion_task_sync

router = APIRouter()


@router.post("/api/notion/webhook")
async def notion_webhook(request: Request) -> JSONResponse:
    """Receive Notion webhook verification and signed task change events."""
    endpoint_secret = str(config.NOTION_WEBHOOK_ENDPOINT_SECRET or "").strip()
    supplied_secret = str(request.query_params.get("key") or "").strip()
    if endpoint_secret and not hmac.compare_digest(endpoint_secret, supplied_secret):
        return JSONResponse({"accepted": False, "error": "Invalid webhook endpoint key"}, status_code=404)

    raw_body = await request.body()
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JSONResponse({"accepted": False, "error": "Invalid JSON payload"}, status_code=400)
    if not isinstance(payload, dict):
        return JSONResponse({"accepted": False, "error": "JSON object is required"}, status_code=400)

    verification_token = str(payload.get("verification_token") or "").strip()
    if verification_token:
        result = notion_task_sync.accept_verification_token(verification_token)
        return JSONResponse(result, status_code=200 if result.get("accepted") else 409)

    signature = request.headers.get("x-notion-signature")
    if not notion_task_sync.verify_webhook_signature(raw_body, signature):
        return JSONResponse({"accepted": False, "error": "Invalid Notion webhook signature"}, status_code=401)

    result = notion_task_sync.enqueue_webhook_event(payload)
    return JSONResponse(result, status_code=200 if result.get("accepted") else 400)
