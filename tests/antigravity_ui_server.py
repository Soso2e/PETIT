"""Real local SDK/model, synthetic DB, no schedulers or account integration."""
from __future__ import annotations
import os
from pathlib import Path
import tempfile

_root = tempfile.TemporaryDirectory(prefix="petit-sdk-browser-")
os.environ.update(PETIT_STORAGE_DIR=_root.name, PETIT_DB_PATH=str(Path(_root.name) / "app.db"),
                  PETIT_MODEL_ROUTING_PATH=str(Path(_root.name) / "routing.json"),
                  PETIT_CHAT_PROFILE="antigravity_sdk", PETIT_ANTIGRAVITY_AUTH="local",
                  PETIT_ANTIGRAVITY_BASE_URL="http://127.0.0.1:1234/v1",
                  PETIT_ANTIGRAVITY_MODEL=os.getenv("PETIT_SDK_TEST_MODEL", "petit-agy-probe"),
                  PETIT_AUTO_SUMMARY_ENABLED="0", PETIT_DAILY_INDEX_ENABLED="0")
from backend import chat, config, conversation_store, db, lifecycle, tools
from backend.app import create_app

config.notion_configured = lambda: False
config.USE_SONA_CORE = False
db.init_db(); conversation_store.ensure_schema(); tools.register_builtin_tools()
tools.dispatch("create_task", {"title": "sdk-browser-fixture"})
lifecycle.startup = lambda: None
lifecycle.shutdown = lambda: None
chat._artifact_executor.submit = lambda *unused: None
app = create_app()
