from backend import lifecycle, main


def test_lifecycle_handlers_are_registered_once() -> None:
    assert main.app.router.on_startup.count(lifecycle.startup) == 1
    assert main.app.router.on_shutdown.count(lifecycle.shutdown) == 1


def test_lifecycle_is_not_implemented_in_main() -> None:
    assert not hasattr(main, "_startup")
    assert not hasattr(main, "_shutdown")
    assert not hasattr(main, "_chroma_sync")
