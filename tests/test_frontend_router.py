from backend import frontend_api, main


def _walk_routes(routes):
    # FastAPI also supports lazily included routers in recent releases.
    for route in routes:
        nested = getattr(route, "original_router", None)
        if nested is not None:
            yield from _walk_routes(nested.routes)
        else:
            yield route


def _routes(path: str, method: str):
    return [
        route
        for route in _walk_routes(main.app.routes)
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


def test_desktop_assets_are_additive_and_share_existing_scripts() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    frontend_api.register(app)
    with TestClient(app) as client:
        root = client.get("/")
        assert root.status_code == 200
        assert "/static/universe.html" in root.text
        overlay = client.get("/static/desktop/index.html")
        assert overlay.status_code == 200
        for script in ("/static/app.js", "/static/voice.js", "/static/session.js"):
            assert script in overlay.text
            assert client.get(script).status_code == 200
        assert "manifest.webmanifest" not in overlay.text
        assert "/static/desktop/" not in client.get("/service-worker.js").text
