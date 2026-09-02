from backend import main, voice


def _routes(path: str, method: str):
    return [
        route
        for route in main.app.routes
        if getattr(route, "path", None) == path
        and method in (getattr(route, "methods", None) or set())
    ]


def test_tts_routes_are_registered_once() -> None:
    status_routes = _routes("/api/tts/status", "GET")
    synth_routes = _routes("/api/tts", "POST")

    assert len(status_routes) == 1
    assert len(synth_routes) == 1
    assert status_routes[0].endpoint is voice.tts_status
    assert synth_routes[0].endpoint is voice.synthesize_speech


def test_tts_endpoints_are_owned_by_voice_module() -> None:
    assert voice.tts_status.__module__ == "backend.voice"
    assert voice.synthesize_speech.__module__ == "backend.voice"
