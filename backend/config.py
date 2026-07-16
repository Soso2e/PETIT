"""Configuration for PETIT. All values can be overridden via environment variables."""
from __future__ import annotations

import os
from pathlib import Path

# Project paths
BASE_DIR = Path(__file__).resolve().parent.parent


def _load_project_env() -> None:
    """Load simple KEY=VALUE entries from the project .env if present."""
    env_file = BASE_DIR / ".env"
    if not env_file.is_file():
        return
    for raw_line in env_file.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        if not separator or not key.strip():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


_load_project_env()
STORAGE_DIR = Path(os.getenv("PETIT_STORAGE_DIR", BASE_DIR / "storage"))
DB_PATH = Path(os.getenv("PETIT_DB_PATH", STORAGE_DIR / "app.db"))
FRONTEND_DIR = BASE_DIR / "frontend"


def _path_from_env(name: str, default: Path) -> Path:
    value = os.getenv(name, "").strip().strip('"')
    return Path(value) if value else default


def _path_list_from_env(name: str) -> list[Path]:
    value = os.getenv(name, "").strip()
    if not value:
        return []
    return [Path(part.strip().strip('"')) for part in value.split(os.pathsep) if part.strip()]


def _list_from_env(name: str) -> list[str]:
    value = os.getenv(name, "").strip()
    if not value:
        return []
    return [part.strip().strip('"') for part in value.split(os.pathsep) if part.strip()]


# Existing Obsidian vaults that PETIT can use as its Markdown brain.
# Windows uses ';' as the separator: C:\VaultA;D:\VaultB
OBSIDIAN_VAULT_DIRS = _path_list_from_env("PETIT_OBSIDIAN_VAULT_DIRS")
PETIT_VAULT_SUBDIR = os.getenv("PETIT_VAULT_SUBDIR", "PETIT").strip().strip("/\\") or "PETIT"
PETIT_VAULT_ROOT = OBSIDIAN_VAULT_DIRS[0] / PETIT_VAULT_SUBDIR if OBSIDIAN_VAULT_DIRS else STORAGE_DIR

# Markdown (Obsidian) export — human-readable / re-usable副本
# AI が検索する正本は SQLite / Chroma 側。md は人が読む・育てる用。
AI_DAILY_DIR = _path_from_env("PETIT_AI_DAILY_DIR", PETIT_VAULT_ROOT / "Daily" if OBSIDIAN_VAULT_DIRS else STORAGE_DIR / "AI_Daily")
AI_MEMORY_DIR = _path_from_env("PETIT_AI_MEMORY_DIR", PETIT_VAULT_ROOT / "Memory" if OBSIDIAN_VAULT_DIRS else STORAGE_DIR / "AI_Memory")

# Server
HOST = os.getenv("PETIT_HOST", "127.0.0.1")
PORT = int(os.getenv("PETIT_PORT", "8000"))

# LM Studio (OpenAI-compatible endpoint)
# LM Studio default local server: http://localhost:1234/v1
LM_BASE_URL = os.getenv("PETIT_LM_BASE_URL", "http://localhost:1234/v1")
LM_API_KEY = os.getenv("PETIT_LM_API_KEY", "lm-studio")  # LM Studio ignores the key
LM_MODEL = os.getenv("PETIT_LM_MODEL", "local-model").strip() or "local-model"
LM_TEMPERATURE = float(os.getenv("PETIT_LM_TEMPERATURE", "0.7"))
LM_TIMEOUT = float(os.getenv("PETIT_LM_TIMEOUT", "120"))
CHAT_MODEL = os.getenv("PETIT_CHAT_MODEL", LM_MODEL).strip() or LM_MODEL
CHAT_BASE_URL = os.getenv("PETIT_CHAT_BASE_URL", LM_BASE_URL).strip() or LM_BASE_URL
CHAT_API_KEY = os.getenv("PETIT_CHAT_API_KEY", LM_API_KEY)
AGENT_MODEL = os.getenv("PETIT_AGENT_MODEL", LM_MODEL).strip() or LM_MODEL
AGENT_BASE_URL = os.getenv("PETIT_AGENT_BASE_URL", LM_BASE_URL).strip() or LM_BASE_URL
AGENT_API_KEY = os.getenv("PETIT_AGENT_API_KEY", LM_API_KEY)
LIGHT_MAX_TOKENS = int(os.getenv("PETIT_LIGHT_MAX_TOKENS", "512"))
ENABLE_THINKING = os.getenv("PETIT_ENABLE_THINKING", "0") not in ("0", "false", "False")

# Agent
MAX_TOOL_ITERATIONS = int(os.getenv("PETIT_MAX_TOOL_ITERATIONS", "2"))

# Sona Agent Core is opt-in while PETIT validates the first vertical slice.
USE_SONA_CORE = os.getenv("PETIT_USE_SONA_CORE", "0") not in ("0", "false", "False")
SONA_CORE_AUDIT_PATH = _path_from_env("PETIT_SONA_CORE_AUDIT_PATH", STORAGE_DIR / "audit" / "sona_agent_core.jsonl")
PETIT_OWNER_ID = os.getenv("PETIT_OWNER_ID", "soso").strip() or "soso"
PETIT_PERSONAL_SCOPE_ID = os.getenv("PETIT_PERSONAL_SCOPE_ID", "soso").strip() or "soso"

# Autonomous summarization (background scheduler)
# 何時間おきに会話を自動でまとめて蓄積するか。2〜3時間 / 1日 などを想定。
AUTO_SUMMARY_ENABLED = os.getenv("PETIT_AUTO_SUMMARY_ENABLED", "1") not in ("0", "false", "False")
SUMMARY_INTERVAL_HOURS = float(os.getenv("PETIT_SUMMARY_INTERVAL_HOURS", "3"))
# この件数未満の未処理会話しかなければ要約をスキップする（無駄なLLM呼び出し回避）
SUMMARY_MIN_CONVERSATIONS = int(os.getenv("PETIT_SUMMARY_MIN_CONVERSATIONS", "1"))
# Episodes are finalized only after a useful boundary.  This deliberately keeps
# ordinary chat on its one-call path; these values are consumed asynchronously.
EPISODE_IDLE_MINUTES = int(os.getenv("PETIT_EPISODE_IDLE_MINUTES", "20"))
EPISODE_MAX_TURNS = int(os.getenv("PETIT_EPISODE_MAX_TURNS", "8"))
EMBEDDING_VERSION = os.getenv("PETIT_EMBEDDING_VERSION", "1")

# Embeddings (for RAG search via LM Studio)
# Load a dedicated embedding model in LM Studio (e.g. nomic-embed-text, bge-m3)
EMBED_BASE_URL = os.getenv("PETIT_EMBED_BASE_URL", LM_BASE_URL)
EMBED_MODEL = os.getenv("PETIT_EMBED_MODEL", "nomic-embed-text")
EMBED_TIMEOUT = float(os.getenv("PETIT_EMBED_TIMEOUT", "30"))
EMBED_RETRY_SECONDS = float(os.getenv("PETIT_EMBED_RETRY_SECONDS", "60"))

# ChromaDB persistent path
CHROMA_PATH = Path(os.getenv("PETIT_CHROMA_PATH", STORAGE_DIR / "chroma"))

# Notion
NOTION_API_KEY = os.getenv("NOTION_API_KEY", "")
NOTION_TASKS_DB_ID = os.getenv("NOTION_TASKS_DB_ID", "")
# Property names in your Notion task DB (customize if your DB uses different names)
NOTION_PROP_TITLE = os.getenv("NOTION_PROP_TITLE", "name")
NOTION_PROP_STATUS = os.getenv("NOTION_PROP_STATUS", "Status")
NOTION_PROP_DUE = os.getenv("NOTION_PROP_DUE", "Date")
NOTION_PROP_PRIORITY = os.getenv("NOTION_PROP_PRIORITY", "Priority")
NOTION_PROP_CATEGORY = os.getenv("NOTION_PROP_CATEGORY", "Category")
NOTION_PROP_REASON = os.getenv("NOTION_PROP_REASON", "reason")
NOTION_PROP_DONE_DATE = os.getenv("NOTION_PROP_DONE_DATE", os.getenv("NOTION_PROP_DONE", "Done"))
# Backward-compatible alias for code or local .env files using the old name.
NOTION_PROP_DONE = NOTION_PROP_DONE_DATE

NOTION_DEFAULT_STATUS = os.getenv("NOTION_DEFAULT_STATUS", "Yet")
NOTION_DONE_STATUS = os.getenv("NOTION_DONE_STATUS", "Done")
NOTION_SYNC_TTL_SECONDS = float(os.getenv("NOTION_SYNC_TTL_SECONDS", "300"))

# Calendar read-only sync.
# Google Calendar can expose private iCal/ICS URLs; local .ics files are also accepted.
CALENDAR_ICS_URLS = _list_from_env("PETIT_CALENDAR_ICS_URLS")
CALENDAR_ICS_FILES = _path_list_from_env("PETIT_CALENDAR_ICS_FILES")
CALENDAR_SYNC_TTL_SECONDS = float(os.getenv("PETIT_CALENDAR_SYNC_TTL_SECONDS", "300"))
TIMETREE_EMAIL = os.getenv("TIMETREE_EMAIL", "")
TIMETREE_PASSWORD = os.getenv("TIMETREE_PASSWORD", "")
TIMETREE_CALENDAR_CODE = os.getenv("TIMETREE_CALENDAR_CODE", "")


def notion_configured() -> bool:
    return bool(NOTION_API_KEY and NOTION_TASKS_DB_ID)


def timetree_configured() -> bool:
    return bool(TIMETREE_EMAIL and TIMETREE_PASSWORD and TIMETREE_CALENDAR_CODE)


# Ensure storage exists
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
