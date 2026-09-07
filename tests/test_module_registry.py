from fastapi import APIRouter, FastAPI
import pytest

from backend import app as app_module
from backend import main
from backend.kernel.modules import ModuleDefinition, ModuleRegistry


def test_module_registry_orders_dependencies_before_dependents() -> None:
    router_a = APIRouter()
    router_b = APIRouter()
    registry = ModuleRegistry(
        (
            ModuleDefinition(id="b", routers=(router_b,), dependencies=("a",)),
            ModuleDefinition(id="a", routers=(router_a,)),
        )
    )

    assert [module.id for module in registry.modules] == ["a", "b"]


def test_module_registry_rejects_duplicate_ids() -> None:
    with pytest.raises(ValueError, match="duplicate module id"):
        ModuleRegistry((ModuleDefinition(id="chat"), ModuleDefinition(id="chat")))


def test_module_registry_rejects_unknown_dependency() -> None:
    with pytest.raises(ValueError, match="unknown module dependency"):
        ModuleRegistry((ModuleDefinition(id="chat", dependencies=("missing",)),))


def test_module_registry_rejects_dependency_cycle() -> None:
    with pytest.raises(ValueError, match="dependency cycle"):
        ModuleRegistry(
            (
                ModuleDefinition(id="a", dependencies=("b",)),
                ModuleDefinition(id="b", dependencies=("a",)),
            )
        )


def test_create_app_registers_existing_api_once() -> None:
    app = app_module.create_app()
    # FastAPI may retain included routers instead of flattening app.routes.
    paths = [getattr(route, "path", None) for module in app_module.build_modules()
             for router in module.routers for route in router.routes]

    assert paths.count("/api/health") == 1
    assert paths.count("/api/chat") == 1
    assert paths.count("/api/actions/{approval_id}") == 1
    assert paths.count("/api/voice") == 1
    assert {"/api/health", "/api/chat", "/api/actions/{approval_id}", "/api/voice"} <= set(app.openapi()["paths"])


def test_main_exposes_registry_built_app() -> None:
    assert isinstance(main.app, FastAPI)
    assert main.app.title == "PETIT"
