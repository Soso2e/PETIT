from backend import main, pending_actions
from backend.chat_models import ChatResponse, PendingAction


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
