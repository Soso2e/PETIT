"""Minimal module registry for PETIT application composition."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from fastapi import APIRouter, FastAPI

AppRegistrar = Callable[[FastAPI], None]


@dataclass(frozen=True)
class ModuleDefinition:
    """Declarative registration contract for one PETIT module."""

    id: str
    routers: tuple[APIRouter, ...] = ()
    registrars: tuple[AppRegistrar, ...] = ()
    dependencies: tuple[str, ...] = ()


class ModuleRegistry:
    """Validate dependencies and register PETIT modules in dependency order."""

    def __init__(self, modules: Iterable[ModuleDefinition]) -> None:
        self._modules = tuple(modules)
        self._by_id = self._index_modules(self._modules)
        self._ordered = self._resolve_order()

    @staticmethod
    def _index_modules(modules: tuple[ModuleDefinition, ...]) -> dict[str, ModuleDefinition]:
        indexed: dict[str, ModuleDefinition] = {}
        for module in modules:
            module_id = module.id.strip()
            if not module_id:
                raise ValueError("module id must not be empty")
            if module_id in indexed:
                raise ValueError(f"duplicate module id: {module_id}")
            indexed[module_id] = module
        return indexed

    def _resolve_order(self) -> tuple[ModuleDefinition, ...]:
        ordered: list[ModuleDefinition] = []
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(module_id: str) -> None:
            if module_id in visited:
                return
            if module_id in visiting:
                raise ValueError(f"module dependency cycle detected at: {module_id}")
            module = self._by_id.get(module_id)
            if module is None:
                raise ValueError(f"unknown module dependency: {module_id}")

            visiting.add(module_id)
            for dependency in module.dependencies:
                if dependency not in self._by_id:
                    raise ValueError(f"unknown module dependency: {module_id} -> {dependency}")
                visit(dependency)
            visiting.remove(module_id)
            visited.add(module_id)
            ordered.append(module)

        for module in self._modules:
            visit(module.id)
        return tuple(ordered)

    @property
    def modules(self) -> tuple[ModuleDefinition, ...]:
        return self._ordered

    def register(self, app: FastAPI) -> None:
        for module in self._ordered:
            for router in module.routers:
                app.include_router(router)
            for registrar in module.registrars:
                registrar(app)
