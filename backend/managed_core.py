"""Run Core under a parent that survives an administrator's restart request."""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import uvicorn

from . import core_restart

RESTART_EXIT_CODE = 75
RELOAD_EXIT_CODE = 76
DISCORD_BOT_MODULE = "backend.channels.discord"


def _discord_bot_env(env_file: str | None, port: int) -> dict[str, str] | None:
    env = os.environ.copy()
    if env_file:
        env_path = Path(env_file)
        if env_path.is_file():
            try:
                from dotenv import dotenv_values
            except ImportError:
                dotenv_values = None
            if dotenv_values is not None:
                for key, value in dotenv_values(env_path).items():
                    if value is not None:
                        env[key] = value
    token = env.get("DISCORD_BOT_TOKEN", "").strip()
    service = env.get("PETIT_DISCORD_SERVICE_TOKEN", "").strip()
    if not token or len(service) < 32:
        return None
    env.setdefault("PETIT_CORE_URL", f"http://127.0.0.1:{port}")
    return env


def _find_discord_bot_pids() -> list[int]:
    my_pid = os.getpid()
    try:
        if sys.platform == "win32":
            ps_cmd = (
                "Get-CimInstance Win32_Process "
                "-Filter \"Name='python.exe' OR Name='pythonw.exe'\" "
                "-ErrorAction SilentlyContinue | "
                f"Where-Object {{ $_.CommandLine -like '*{DISCORD_BOT_MODULE}*' }} | "
                "Select-Object -ExpandProperty ProcessId"
            )
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=10, check=False,
            )
            if result.returncode != 0:
                return []
            pids = []
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.isdigit():
                    pid = int(line)
                    if pid != my_pid:
                        pids.append(pid)
            return pids
        result = subprocess.run(
            ["ps", "-eo", "pid=,args="],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if result.returncode != 0:
            return []
        pids = []
        for line in result.stdout.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) == 2 and parts[0].isdigit() and DISCORD_BOT_MODULE in parts[1]:
                pid = int(parts[0])
                if pid != my_pid:
                    pids.append(pid)
        return pids
    except Exception:
        return []


def _stop_discord_bot(managed_proc: subprocess.Popen | None) -> None:
    if managed_proc is not None and managed_proc.poll() is None:
        try:
            managed_proc.terminate()
            managed_proc.wait(timeout=5)
        except Exception:
            try:
                managed_proc.kill()
                managed_proc.wait(timeout=5)
            except Exception:
                pass


def _wait_for_core_health(port: int, stop_event: threading.Event, timeout_seconds: float = 30.0) -> bool:
    url = f"http://127.0.0.1:{port}/api/health"
    end_time = time.monotonic() + timeout_seconds
    while not stop_event.is_set() and time.monotonic() < end_time:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError, TimeoutError):
            pass
        stop_event.wait(0.5)
    return False


def _start_discord_bot(env: dict[str, str]) -> subprocess.Popen | None:
    kwargs: dict = {
        "env": env,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        return subprocess.Popen([sys.executable, "-m", DISCORD_BOT_MODULE], **kwargs)
    except OSError:
        return None


def _ensure_discord_bot_when_ready(
    port: int,
    env: dict[str, str],
    stop_event: threading.Event,
    managed_bot: list[subprocess.Popen | None],
) -> None:
    if not _wait_for_core_health(port, stop_event):
        return
    if stop_event.is_set():
        return
    current = managed_bot[0]
    if current is not None and current.poll() is None:
        return
    if _find_discord_bot_pids():
        return
    managed_bot[0] = _start_discord_bot(env)


async def serve(args):
    core_restart.managed = True
    core_restart.development_mode = args.reload
    reload_requested = asyncio.Event()
    server = uvicorn.Server(uvicorn.Config(
        "backend.main:app", host="127.0.0.1", port=args.port, env_file=args.env_file,
        timeout_graceful_shutdown=15,
    ))

    async def wait_for_restart():
        while not (core_restart.requested.is_set() or reload_requested.is_set()):
            await asyncio.sleep(0.2)
        # Give the HTTP response time to reach the browser before shutting down.
        await asyncio.sleep(0.5)
        server.should_exit = True

    async def watch_backend():
        from watchfiles import PythonFilter, awatch
        async for _ in awatch(Path(__file__).resolve().parent, watch_filter=PythonFilter()):
            reload_requested.set()
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
    if core_restart.requested.is_set():
        return RESTART_EXIT_CODE
    return RELOAD_EXIT_CODE if reload_requested.is_set() else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--env-file")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        return asyncio.run(serve(args))

    command = [sys.executable, "-m", "backend.managed_core", "--worker", "--port", str(args.port)]
    if args.env_file is not None:
        command.extend(["--env-file", args.env_file])
    reload_enabled = args.reload
    managed_bot: list[subprocess.Popen | None] = [None]
    ensure_discord = True
    try:
        while True:
            worker_command = [*command, "--reload"] if reload_enabled else command
            stop_bot_wait = threading.Event()
            bot_thread: threading.Thread | None = None
            if ensure_discord:
                bot_env = _discord_bot_env(args.env_file, args.port)
                if bot_env is not None:
                    bot_thread = threading.Thread(
                        target=_ensure_discord_bot_when_ready,
                        args=(args.port, bot_env, stop_bot_wait, managed_bot),
                        daemon=True,
                    )
                    bot_thread.start()
            try:
                code = subprocess.call(worker_command)
            finally:
                stop_bot_wait.set()
                if bot_thread is not None:
                    bot_thread.join(timeout=2)
            if code == RESTART_EXIT_CODE:
                reload_enabled = False
                _stop_discord_bot(managed_bot[0])
                managed_bot[0] = None
                ensure_discord = True
            elif code == RELOAD_EXIT_CODE:
                ensure_discord = False
            else:
                return code
    except KeyboardInterrupt:
        return 130
    finally:
        _stop_discord_bot(managed_bot[0])


if __name__ == "__main__":
    raise SystemExit(main())
