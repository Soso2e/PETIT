"""Environment-backed settings for PETIT's read-only Linkraft adapter."""
from __future__ import annotations

import os

BASE_URL = os.getenv("LINKRAFT_BASE_URL", "").strip().rstrip("/")
READ_TOKEN = os.getenv("LINKRAFT_PETIT_READ_TOKEN", "").strip()
SYNC_TTL_SECONDS = float(os.getenv("LINKRAFT_SYNC_TTL_SECONDS", "300"))


def configured() -> bool:
    return bool(BASE_URL and READ_TOKEN)
