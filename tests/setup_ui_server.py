"""Isolated real HTTP application for setup tests. Synthetic data only.

PETIT_SETUP_REAL_PROVIDER=1 disables the synthetic provider. No account is borrowed.
"""
import os
from pathlib import Path
import tempfile

_temp = tempfile.TemporaryDirectory(prefix="petit-setup-ui-")
_root = Path(os.getenv("PETIT_SETUP_TEST_ROOT", _temp.name))
_root.mkdir(parents=True, exist_ok=True)
os.environ.update(PETIT_STORAGE_DIR=str(_root), PETIT_SETTINGS_DIR=str(_root / "settings"),
                  PETIT_BOOTSTRAP_TOKEN="",
                  PETIT_DB_PATH=str(_root / "app.db"), PETIT_MODEL_ROUTING_PATH=str(_root / "routing.json"),
                  PETIT_AUTO_SUMMARY_ENABLED="0", PETIT_DAILY_INDEX_ENABLED="0",
                  PETIT_ANTIGRAVITY_ACP_EXECUTABLE=str(_root / "missing-acp.exe"))

from backend import config, db, lifecycle, conversation_store, chat, tools
from backend import antigravity_acp
antigravity_acp.DEFAULT_ROOT = _root / "antigravity-acp"
from backend.app import create_app

config.notion_configured = lambda: False
config.USE_SONA_CORE = False
db.init_db(); conversation_store.ensure_schema(); tools.register_builtin_tools()
from backend import task_sync_queue, notion_task_sync
task_sync_queue.ensure_task_sync_schema(); notion_task_sync.ensure_schema()
from backend import task_hierarchy
task_hierarchy.ensure_task_hierarchy_schema()
lifecycle.startup = lambda: None
lifecycle.shutdown = lambda: None
chat._artifact_executor.submit = lambda *args: None

if os.getenv("PETIT_SETUP_REAL_PROVIDER") != "1":
    from backend import lmstudio_client, brain_priority
    def synthetic(messages, **kwargs):
        return {"role": "assistant", "content": "合成Providerの返答"}
    lmstudio_client.chat_completion = synthetic

app = create_app()
