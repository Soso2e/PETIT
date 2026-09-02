from backend import main, model_routing_api


def _routes(path: str, method: str):
    return [
        route
        for route in main.app.routes
        if getattr(route, "path", None) == path
        and method in (getattr(route, "methods", None) or set())
    ]


def test_model_routing_routes_are_registered_once() -> None:
    get_routes = _routes("/api/model-routing", "GET")
    post_routes = _routes("/api/model-routing", "POST")

    assert len(get_routes) == 1
    assert len(post_routes) == 1
    assert get_routes[0].endpoint is model_routing_api.get_model_routing
    assert post_routes[0].endpoint is model_routing_api.update_model_routing


def test_model_routing_endpoints_owned_by_router_module() -> None:
    assert model_routing_api.get_model_routing.__module__ == "backend.model_routing_api"
    assert model_routing_api.update_model_routing.__module__ == "backend.model_routing_api"
    assert not hasattr(main, "get_model_routing")
    assert not hasattr(main, "update_model_routing")
    assert not hasattr(main, "ModelRoutingUpdate")
