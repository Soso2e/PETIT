from __future__ import annotations

import subprocess
import sys

from backend import app as app_module, tools


def _run_python(code: str) -> str:
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_importing_tools_package_does_not_register_builtins() -> None:
    output = _run_python(
        "from backend import tools; print(len(tools.registered_names()))"
    )
    assert output == "0"


def test_create_app_registers_builtin_tools_explicitly() -> None:
    output = _run_python(
        "from backend.app import create_app; from backend import tools; "
        "create_app(); print(len(tools.registered_names()))"
    )
    assert int(output) > 0


def test_builtin_tools_module_precedes_tool_consumers() -> None:
    modules = {module.id: module for module in app_module.build_modules()}

    assert "builtin-tools" in modules
    assert "builtin-tools" in modules["pending-actions"].dependencies
    assert "builtin-tools" in modules["chat"].dependencies


def test_builtin_catalog_keeps_web_tools_explicit() -> None:
    assert "backend.web_tools" in tools.builtin_module_names()
