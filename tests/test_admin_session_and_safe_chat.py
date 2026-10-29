import json
from unittest.mock import Mock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend import (setup_store as settings, setup_api, chat, conversation_api,
                     config, db, conversation_store as store, tools, service_sync as sync)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("PETIT_SETTINGS_DIR", str(tmp_path / "settings"))
    monkeypatch.delenv("PETIT_BOOTSTRAP_TOKEN", raising=False)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "app.db")
    monkeypatch.setattr("backend.chat._artifact_executor.submit", Mock())
    monkeypatch.setattr("backend.chroma_client.add", Mock())
    monkeypatch.setattr("backend.chroma_client.sync_structured_data", Mock())
    setup_api._attempts.clear()
    settings._sessions.clear()
    db.init_db()
    store.ensure_schema()
    sync.ensure_schema()
    tools.register_builtin_tools()
    settings.set_password("test-password-1234")
    settings.update({"completed": True})


@pytest.fixture
def app_client():
    app = FastAPI()
    app.include_router(setup_api.router)
    app.include_router(chat.router)
    app.include_router(conversation_api.router)
    setup_api.install(app)
    return TestClient(app, headers={"Origin": "http://testserver"})


def test_admin_session_persists_in_db_across_memory_clears():
    token = settings.authenticate("test-password-1234")
    assert token is not None
    assert settings.valid_session(token) is True

    # Memory cache is purged (simulating server reload/restart)
    settings._sessions.clear()
    assert len(settings._sessions) == 0

    # DB lookup restores session
    assert settings.valid_session(token) is True

    # Logout purges both memory and DB
    settings.logout(token)
    assert settings.valid_session(token) is False

    settings._sessions.clear()
    assert settings.valid_session(token) is False


def test_unauthenticated_chat_allowed_and_tools_disabled(app_client, monkeypatch):
    captured_tools = []

    def mock_chat_completion(messages, tools=None, **kwargs):
        captured_tools.append(tools)
        return {"role": "assistant", "content": "こんにちは！ツールなしの会話です。"}

    monkeypatch.setattr("backend.lmstudio_client.chat_completion", mock_chat_completion)

    # 1. Unauthenticated chat request (no petit_admin cookie)
    res = app_client.post("/api/chat", json={"message": "こんにちは"})
    assert res.status_code == 200
    data = res.json()
    assert data["reply"] == "こんにちは！ツールなしの会話です。"
    # No tools should be passed to LLM
    assert len(captured_tools) == 1
    assert captured_tools[0] is None

    # 2. Authenticated chat request with admin cookie
    token = settings.authenticate("test-password-1234")
    app_client.cookies.set("petit_admin", token)
    captured_tools.clear()

    res = app_client.post("/api/chat", json={"message": "予定を教えて"})
    assert res.status_code == 200
    # Tools should be provided when authenticated as admin
    assert len(captured_tools) == 1
    assert captured_tools[0] is not None
    assert len(captured_tools[0]) > 0

    # 3. Logout via API -> subsequent chat loses tool access
    logout_res = app_client.post("/api/setup/logout")
    assert logout_res.status_code == 200
    app_client.cookies.delete("petit_admin")
    captured_tools.clear()

    res = app_client.post("/api/chat", json={"message": "こんにちは"})
    assert res.status_code == 200
    assert len(captured_tools) == 1
    assert captured_tools[0] is None


def test_unauthenticated_blocked_from_admin_endpoints(app_client):
    # Unauthenticated -> 401
    res = app_client.get("/api/setup/config")
    assert res.status_code == 401

    # Login -> Authenticated
    token = settings.authenticate("test-password-1234")
    app_client.cookies.set("petit_admin", token)

    res = app_client.get("/api/setup/config")
    assert res.status_code == 200
