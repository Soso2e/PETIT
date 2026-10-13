from backend import health, main


def test_health_route_is_registered_once() -> None:
    # FastAPI may retain included routers lazily rather than flatten app.routes.
    def routes(router):
        for route in router.routes:
            included = getattr(route, "original_router", None)
            if included is not None:
                yield from routes(included)
            else:
                yield route

    health_routes = [
        route
        for route in routes(main.app)
        if getattr(route, "path", None) == "/api/health"
        and "GET" in (getattr(route, "methods", None) or set())
    ]

    assert len(health_routes) == 1
    assert health_routes[0].endpoint is health.health


def test_health_endpoint_owned_by_health_module() -> None:
    assert health.health.__module__ == "backend.health"
    assert health.health.__name__ == "health"
