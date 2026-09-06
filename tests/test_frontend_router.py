from backend import frontend_api, main


def _routes(path: str, method: str):
    return [
        route
        for route in main.app.routes
        if getattr(route, "path", None) == path
        and method in (getattr(route, "methods", None) or set())
    ]


def test_frontend_routes_are_registered_once() -> None:
    root_routes = _routes("/", "GET")
    service_worker_routes = _routes("/service-worker.js", "GET")
    sw_alias_routes = _routes("/sw.js", "GET")

    assert len(root_routes) == 1
    assert len(service_worker_routes) == 1
    assert len(sw_alias_routes) == 1
    assert root_routes[0].endpoint is frontend_api.index
    assert service_worker_routes[0].endpoint is frontend_api.service_worker
    assert sw_alias_routes[0].endpoint is frontend_api.service_worker


def test_frontend_routes_are_not_owned_by_main() -> None:
    assert not hasattr(main, "index")
    assert not hasattr(main, "service_worker")


def test_static_mount_is_registered_once() -> None:
    static_routes = [route for route in main.app.routes if getattr(route, "path", None) == "/static"]
    assert len(static_routes) == 1
