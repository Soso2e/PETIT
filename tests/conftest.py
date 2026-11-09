"""Shared test isolation."""
import pytest


@pytest.fixture(autouse=True)
def _isolated_petit_home(tmp_path, monkeypatch):
    # Never create or read the real ~/PETIT-Home from tests.
    monkeypatch.setenv("PETIT_HOME", str(tmp_path / "petit-home"))
