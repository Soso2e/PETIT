from backend import main, notion_webhook


def test_notion_webhook_route_is_registered_once() -> None:
    routes = [
        route
        for route in main.app.routes
        if getattr(route, "path", None) == "/api/notion/webhook"
        and "POST" in (getattr(route, "methods", None) or set())
    ]

    assert len(routes) == 1
    assert routes[0].endpoint is notion_webhook.notion_webhook


def test_notion_webhook_endpoint_owned_by_module() -> None:
    assert notion_webhook.notion_webhook.__module__ == "backend.notion_webhook"
