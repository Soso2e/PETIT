"""Synthetic provider + temporary DB for the real browser smoke test only."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

_directory = tempfile.TemporaryDirectory(prefix="petit-renaissance-ui-")
os.environ["PETIT_STORAGE_DIR"] = _directory.name
os.environ["PETIT_DB_PATH"] = str(Path(_directory.name) / "app.db")
os.environ["PETIT_AUTO_SUMMARY_ENABLED"] = "0"
os.environ["PETIT_DAILY_INDEX_ENABLED"] = "0"

from backend import brain, chat, config, conversation_store, db, lifecycle, tools
from backend.app import create_app

config.notion_configured = lambda: False
config.USE_SONA_CORE = False
db.init_db()
conversation_store.ensure_schema()
task = json.loads(tools.dispatch("create_task", {"title": "受入用の卒研タスク"}))["task"]
lifecycle.startup = lambda: None
lifecycle.shutdown = lambda: None
chat._artifact_executor.submit = lambda *args: None


def fixture_model(messages, **kwargs):
    if messages[-1]["role"] == "tool":
        return {"role": "assistant", "content": "実行結果を確認しました。"}
    message = messages[-1]["content"]
    name = "add_schedule" if message == "予定を追加" else "start_work_session"
    arguments = ({"title": "受入用発表", "start_time": "2026-11-02T10:00:00+09:00"}
                 if name == "add_schedule" else {"task_id": str(task["id"])})
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": "fixture-call", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}]}


brain.lmstudio_client.chat_completion = fixture_model
app = create_app()
