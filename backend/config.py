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

# Ensure storage exists
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
