"""Run Core under a parent that survives an administrator's restart request."""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import subprocess
import sys

import uvicorn

from . import core_restart

RESTART_EXIT_CODE = 75


async def serve(args):
    core_restart.managed = True
    server = uvicorn.Server(uvicorn.Config(
        "backend.main:app", host="127.0.0.1", port=args.port, env_file=args.env_file,
        timeout_graceful_shutdown=15,
    ))

    async def wait_for_restart():
        while not core_restart.requested.is_set():
            await asyncio.sleep(0.2)
        # Give the HTTP response time to reach the browser before shutting down.
        await asyncio.sleep(0.5)
        server.should_exit = True

    async def watch_backend():
        from watchfiles import PythonFilter, awatch
        async for _ in awatch(Path(__file__).resolve().parent, watch_filter=PythonFilter()):
            core_restart.requested.set()
            return

    tasks = [asyncio.create_task(wait_for_restart())]
    if args.reload:
        tasks.append(asyncio.create_task(watch_backend()))
    try:
        await server.serve()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    if not server.started:
        return 1
    return RESTART_EXIT_CODE if core_restart.requested.is_set() else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--env-file")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        return asyncio.run(serve(args))

    command = [sys.executable, "-m", "backend.managed_core", *sys.argv[1:], "--worker"]
    try:
        while True:
            code = subprocess.call(command)
            if code != RESTART_EXIT_CODE:
                return code
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
