from backend import health, main


def test_health_route_is_registered_once() -> None:
    health_routes = [
        route
        for route in main.app.routes
        if getattr(route, "path", None) == "/api/health"
        and "GET" in (getattr(route, "methods", None) or set())
    ]

    assert len(health_routes) == 1
    assert health_routes[0].endpoint is health.health


def test_health_endpoint_owned_by_health_module() -> None:
    assert health.health.__module__ == "backend.health"
    assert not hasattr(main, "health")
