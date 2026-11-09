"""Development folders authorized by the administrator or server configuration."""
import os
from pathlib import Path

from . import config, setup_store


def configured(setup=None):
    ui = (setup_store.load() if setup is None else setup).get("coding_roots", [])
    result = {}
    for path, source in [(p, "settings") for p in ui] + [(p, "environment") for p in config.WORKSPACE_CONTEXT_DIRS]:
        key = os.path.normcase(str(Path(path).expanduser().absolute()))
        result[key] = (str(path), source)
    return list(result.values())
