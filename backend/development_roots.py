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


def extra_folders(repository_path: str, setup=None) -> list[str]:
    """Return additional working folder paths linked to a registered repository."""
    if not repository_path:
        return []
    raw = (setup_store.load() if setup is None else setup).get("coding_root_extras") or {}
    if not isinstance(raw, dict):
        return []
    target = os.path.normcase(str(Path(repository_path).expanduser().absolute()))
    seen = set()
    result = []
    for key, paths in raw.items():
        if os.path.normcase(str(Path(key).expanduser().absolute())) != target:
            continue
        if not isinstance(paths, list):
            continue
        for item in paths:
            norm = os.path.normcase(str(Path(item).expanduser().absolute()))
            if norm not in seen:
                seen.add(norm)
                result.append(str(item))
    return result
