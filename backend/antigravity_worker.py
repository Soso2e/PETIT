"""Private SDK process protocol. Invoke only through antigravity_brain.run_isolated.

Configuration travels over a local pipe, never command-line arguments or logs.
Core remains the sole owner of Turn acceptance, replay, and final response storage.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
import sys


def main() -> int:
    logging.disable(logging.CRITICAL)
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        payload = json.load(sys.stdin)
        from . import antigravity_brain as sdk, config, model_routing, tools
        config.DB_PATH = Path(payload["db_path"])
        model_routing.STATE_PATH = Path(payload["routing_path"])
        if payload.get("settings_path"):
            os.environ["PETIT_SETTINGS_DIR"] = payload["settings_path"]
            from . import setup_store, brain_priority
            setup_store.apply_runtime()
            if payload["target"].get("core_tools"):
                brain_priority._active.set(payload["target"])
        tools.register_builtin_tools()
        used, metadata = [], {}
        reply = asyncio.run(sdk.execute_sdk(payload["request_id"], payload["target"],
                            payload["instructions"], payload["prompt"], used, metadata))
        result = {"ok": True, "reply": reply, "used_tools": used, "metadata": metadata}
    except BaseException as exc:
        result = {"ok": False, "error_type": type(exc).__name__}
    sys.stdout.write(json.dumps(result, ensure_ascii=True) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
