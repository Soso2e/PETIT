"""Configuration for PETIT. All values can be overridden via environment variables."""
from __future__ import annotations

import os
from pathlib import Path

# Project paths
BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = Path(os.getenv("PETIT_STORAGE_DIR", BASE_DIR / "storage"))
DB_PATH = Path(os.getenv("PETIT_DB_PATH", STORAGE_DIR / "app.db"))
FRONTEND_DIR = BASE_DIR / "frontend"

# Markdown (Obsidian) export — human-readable / re-usable副本
# AI が検索する正本は SQLite / Chroma 側。md は人が読む・育てる用。
AI_DAILY_DIR = Path(os.getenv("PETIT_AI_DAILY_DIR", STORAGE_DIR / "AI_Daily"))
AI_MEMORY_DIR = Path(os.getenv("PETIT_AI_MEMORY_DIR", STORAGE_DIR / "AI_Memory"))

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

# Autonomous summarization (background scheduler)
# 何時間おきに会話を自動でまとめて蓄積するか。2〜3時間 / 1日 などを想定。
AUTO_SUMMARY_ENABLED = os.getenv("PETIT_AUTO_SUMMARY_ENABLED", "1") not in ("0", "false", "False")
SUMMARY_INTERVAL_HOURS = float(os.getenv("PETIT_SUMMARY_INTERVAL_HOURS", "3"))
# この件数未満の未処理会話しかなければ要約をスキップする（無駄なLLM呼び出し回避）
SUMMARY_MIN_CONVERSATIONS = int(os.getenv("PETIT_SUMMARY_MIN_CONVERSATIONS", "1"))

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
# Property names in your Notion task DB (customize if your DB uses different names)
NOTION_PROP_TITLE = os.getenv("NOTION_PROP_TITLE", "name")
NOTION_PROP_STATUS = os.getenv("NOTION_PROP_STATUS", "Status")
NOTION_PROP_DUE = os.getenv("NOTION_PROP_DUE", "Date")
NOTION_PROP_PRIORITY = os.getenv("NOTION_PROP_PRIORITY", "優先度")
NOTION_PROP_CATEGORY = os.getenv("NOTION_PROP_CATEGORY", "Category")
NOTION_PROP_REASON = os.getenv("NOTION_PROP_REASON", "reason")
NOTION_PROP_DONE = os.getenv("NOTION_PROP_DONE", "Done")

NOTION_DEFAULT_STATUS = os.getenv("NOTION_DEFAULT_STATUS", "Yet")
NOTION_DONE_STATUS = os.getenv("NOTION_DONE_STATUS", "Done")


def notion_configured() -> bool:
    return bool(NOTION_API_KEY and NOTION_TASKS_DB_ID)


# Ensure storage exists
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
