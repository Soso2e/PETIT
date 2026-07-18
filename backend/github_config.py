"""Environment-backed settings for PETIT's read-only GitHub evidence adapter."""
from __future__ import annotations

import os

API_URL = os.getenv("PETIT_GITHUB_API_URL", "https://api.github.com").rstrip("/")
TOKEN = os.getenv("PETIT_GITHUB_TOKEN", "").strip()
API_VERSION = os.getenv("PETIT_GITHUB_API_VERSION", "2022-11-28").strip() or "2022-11-28"
SYNC_TTL_SECONDS = float(os.getenv("PETIT_GITHUB_SYNC_TTL_SECONDS", "300"))
INITIAL_LOOKBACK_DAYS = max(1, int(os.getenv("PETIT_GITHUB_INITIAL_LOOKBACK_DAYS", "30")))
MAX_PAGES = max(1, min(10, int(os.getenv("PETIT_GITHUB_MAX_PAGES", "3"))))
MAX_CHECK_COMMITS = max(1, min(100, int(os.getenv("PETIT_GITHUB_MAX_CHECK_COMMITS", "50"))))


def configured() -> bool:
    """Private-repository capable configuration requires an explicit token."""
    return bool(TOKEN)
