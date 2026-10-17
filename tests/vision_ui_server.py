"""Isolated UI fixture server; no real provider, personal DB or background workers.

Run: python -m uvicorn tests.vision_ui_server:app --host 127.0.0.1 --port 18763
"""
import json
import tempfile
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend import attachments, brain_runtime, chat, config, db, frontend_api, lmstudio_client

_temporary = tempfile.TemporaryDirectory(prefix="petit-vision-ui-")
config.STORAGE_DIR = Path(_temporary.name)
config.DB_PATH = config.STORAGE_DIR / "test.db"
db.init_db()


def fixture_completion(messages, **kwargs):
    if isinstance(messages[-1].get("content"), list):
        images = []
        for block in messages[-1]["content"]:
            if block["type"] == "text":
                images.append({"attachment_id": block["text"].split(": ")[1], "legibility": "clear",
                               "description": "Steam statistics fixture", "texts": [], "metrics": [],
                               "tables": [], "project_candidates": [], "uncertainties": []})
        return {"content": json.dumps({"images": images})}
    if any(item.get("content") == "simulate-failure" for item in messages):
        raise lmstudio_client.LMStudioError("テスト用の画像解析エラー")
    return {"content": "画像を読んだよ。これは機密なしのUIテスト画像です。"}


lmstudio_client.chat_completion = fixture_completion
brain_runtime.chat_completion = fixture_completion
lmstudio_client.endpoint = lambda route: {"provider": "lm_studio", "external": False, "base_url": "http://localhost:1234/v1", "profile": "local", "model": "fixture"}
chat.conversation_state.update_after_turn = lambda *args, **kwargs: None


@asynccontextmanager
async def lifespan(app):
    yield
    _temporary.cleanup()


app = FastAPI(lifespan=lifespan)
app.include_router(attachments.router)
app.include_router(chat.router)
frontend_api.register(app)
