from backend import main, pending_actions
from backend.chat_models import ActionDecision, ChatResponse, PendingAction


def _clear_pending_actions() -> None:
    with pending_actions._pending_actions_lock:
        pending_actions._pending_actions.clear()


def test_pending_action_route_is_registered_once() -> None:
    routes = [
        route
        for route in main.app.routes
        if getattr(route, "path", None) == "/api/actions/{approval_id}"
        and "POST" in (getattr(route, "methods", None) or set())
    ]

    assert len(routes) == 1
    assert routes[0].endpoint is pending_actions.decide_action


def test_pending_action_endpoint_owned_by_module() -> None:
    assert pending_actions.decide_action.__module__ == "backend.pending_actions"
    assert pending_actions.register.__module__ == "backend.pending_actions"


def test_chat_models_are_shared_outside_main() -> None:
    assert ChatResponse.__module__ == "backend.chat_models"
    assert PendingAction.__module__ == "backend.chat_models"


def test_pending_action_can_be_cancelled() -> None:
    _clear_pending_actions()
    registered = pending_actions.register([{"name": "example_write", "arguments": {"value": 1}}])

    response = pending_actions.decide_action(
        registered[0].approval_id,
        ActionDecision(approved=False),
    )

    assert response.reply == "書き込みをキャンセルしました。"
    assert response.error is None
    _clear_pending_actions()


def test_pending_action_dispatches_after_approval(monkeypatch) -> None:
    _clear_pending_actions()
    registered = pending_actions.register([{"name": "example_write", "arguments": {"value": 1}}])
    calls: list[tuple[str, dict[str, int]]] = []

    def fake_dispatch(name: str, arguments: dict[str, int]) -> str:
        calls.append((name, arguments))
        return '{"saved": true}'

    monkeypatch.setattr(pending_actions.tools, "dispatch", fake_dispatch)
    response = pending_actions.decide_action(
        registered[0].approval_id,
        ActionDecision(approved=True),
    )

    assert calls == [("example_write", {"value": 1})]
    assert response.error is None
    assert response.used_tools == [{"name": "example_write", "arguments": {"value": 1}}]
    _clear_pending_actions()
