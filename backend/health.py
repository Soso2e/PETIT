"""System health API router.

This module owns the existing /api/health endpoint without changing its
response contract. It is intentionally kept close to the current backend
layout while PETIT moves toward the modular architecture tracked in #227.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from . import (
    aivis_speech,
    calendar_providers,
    calendar_sync,
    chroma_client,
    config,
    db,
    lmstudio_client,
    markdown_export,
    model_routing,
    notion_task_sync,
    notifications,
    tools,
    vault_indexer,
)

router = APIRouter()


@router.get("/api/health")
def health() -> dict[str, Any]:
    """Return the existing PETIT health payload unchanged."""
    chat_health = lmstudio_client.health("chat")
    agent_health = lmstudio_client.health("agent")
    try:
        mem_count = chroma_client._collection("petit_memory").count()
        conv_count = chroma_client._collection("petit_conversations").count()
        episode_count = chroma_client._collection("petit_episodes").count()
        vault_count = chroma_client._collection("petit_vault").count()
        rag_info: dict[str, Any] = {
            "available": True,
            "embed_model": config.EMBED_MODEL,
            "indexed": {
                "memory": mem_count,
                "conversations_legacy": conv_count,
                "episodes": episode_count,
                "vault": vault_count,
            },
            "embedding_stats": chroma_client.embedding_stats(),
        }
    except Exception:  # noqa: BLE001
        rag_info = {"available": False, "embed_model": config.EMBED_MODEL}

    with db.get_connection() as conn:
        calendar_cached = int(
            conn.execute("SELECT COUNT(*) FROM calendar_events_cache").fetchone()[0]
        )

    routing_status = model_routing.public_status()
    return {
        "status": "ok",
        "tools": tools.registered_names(),
        # `lm_studio` is retained for older clients; new clients use the two
        # explicit model entries below.
        "lm_studio": {
            "ok": chat_health["server_ok"],
            "models": chat_health.get("models", []),
            "base_url": chat_health["base_url"],
        },
        "chat_model": chat_health,
        "agent_model": agent_health
        | {"fallback_available": bool(chat_health["server_ok"])},
        "notion": {
            "configured": config.notion_configured(),
            "sync": __import__("backend.tools.notion", fromlist=["status"]).status(),
            "task_live_sync": notion_task_sync.status(),
        },
        "rag": rag_info,
        "auto_summary": {
            "enabled": config.AUTO_SUMMARY_ENABLED,
            "interval_hours": config.SUMMARY_INTERVAL_HOURS,
            "summaries": len(db.recent_summaries(limit=1000)),
            "episodes": len(db.recent_episodes(limit=1000)),
        },
        "markdown": markdown_export.status(),
        "obsidian_vault": vault_indexer.status(),
        "calendar": {
            **calendar_sync.status(),
            "cached_events": calendar_cached,
            "google_calendar_connected_to_petit": calendar_sync.configured(),
            "read_adapter": "ics",
            "write_providers": calendar_providers.available(),
        },
        "brain": vault_indexer.status(),
        "memory": {
            "episodes": len(db.recent_episodes(limit=1000)),
            "long_term": len(db.all_memory()),
        },
        "model_routing": {
            **routing_status,
            "chat_model": chat_health["model"],
            "agent_model": agent_health["model"],
        },
        "tts": aivis_speech.status(check_engine=False),
        "notifications": notifications.notification_status(),
    }
