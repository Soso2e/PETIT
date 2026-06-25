"""Configuration for PETIT. All values can be overridden via environment variables."""
from __future__ import annotations

import os
from pathlib import Path

# Project paths
BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = Path(os.getenv("PETIT_STORAGE_DIR", BASE_DIR / "storage"))
DB_PATH = Path(os.getenv("PETIT_DB_PATH", STORAGE_DIR / "app.db"))
FRONTEND_DIR = BASE_DIR / "frontend"

# Server
HOST = os.getenv("PETIT_HOST", "127.0.0.1")
PORT = int(os.getenv("PETIT_PORT", "8000"))

# LM Studio (OpenAI-compatible endpoint)
# LM Studio default local server: http://localhost:1234/v1
LM_BASE_URL = os.getenv("PETIT_LM_BASE_URL", "http://localhost:1234/v1")
LM_API_KEY = os.getenv("PETIT_LM_API_KEY", "lm-studio")  # LM Studio ignores the key
LM_MODEL = os.getenv("PETIT_LM_MODEL", "local-model")
LM_TEMPERATURE = float(os.getenv("PETIT_LM_TEMPERATURE", "0.7"))
LM_TIMEOUT = float(os.getenv("PETIT_LM_TIMEOUT", "120"))

# Agent
MAX_TOOL_ITERATIONS = int(os.getenv("PETIT_MAX_TOOL_ITERATIONS", "5"))

# Embeddings (for RAG search via LM Studio)
# Load a dedicated embedding model in LM Studio (e.g. nomic-embed-text, bge-m3)
EMBED_BASE_URL = os.getenv("PETIT_EMBED_BASE_URL", LM_BASE_URL)
EMBED_MODEL = os.getenv("PETIT_EMBED_MODEL", "nomic-embed-text")
EMBED_TIMEOUT = float(os.getenv("PETIT_EMBED_TIMEOUT", "30"))

# ChromaDB persistent path
CHROMA_PATH = Path(os.getenv("PETIT_CHROMA_PATH", STORAGE_DIR / "chroma"))

# Notion
NOTION_API_KEY = os.getenv("NOTION_API_KEY", "")
NOTION_TASKS_DB_ID = os.getenv("NOTION_TASKS_DB_ID", "")
# Property names in your Notion DB (customize if your DB uses different names)
NOTION_PROP_TITLE = os.getenv("NOTION_PROP_TITLE", "名前")
NOTION_PROP_STATUS = os.getenv("NOTION_PROP_STATUS", "ステータス")
NOTION_PROP_DUE = os.getenv("NOTION_PROP_DUE", "期日")
NOTION_PROP_PRIORITY = os.getenv("NOTION_PROP_PRIORITY", "優先度")


def notion_configured() -> bool:
    return bool(NOTION_API_KEY and NOTION_TASKS_DB_ID)


# Ensure storage exists
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
