from backend import chat, main, shortcut_voice


def _chat_routes():
    return [
        route
        for route in main.app.routes
        if getattr(route, "path", None) == "/api/chat"
        and "POST" in (getattr(route, "methods", None) or set())
    ]


def test_chat_route_is_registered_once() -> None:
    routes = _chat_routes()

    assert len(routes) == 1
    assert routes[0].endpoint is chat.chat


def test_chat_endpoint_owned_by_chat_module() -> None:
    assert chat.chat.__module__ == "backend.chat"
    assert chat.ChatRequest.__module__ == "backend.chat"


def test_empty_chat_keeps_existing_error_contract() -> None:
    response = chat.chat(chat.ChatRequest(message=""))

    assert response.reply == ""
    assert response.error == "メッセージが空です。"
    assert response.request_id


def test_voice_shortcut_uses_shared_chat_module() -> None:
    assert shortcut_voice.chat is chat
