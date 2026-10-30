"""Shared provider boundary helpers; no provider SDK dependency."""
from __future__ import annotations
import json
import os
import subprocess

RETIRED_SDK_MESSAGE = "Antigravity SDKは廃止されました。設定で利用するAIを明示的に再選択してください。既存設定と履歴は保持しています。"

def provider_identity(target: dict) -> tuple:
    return tuple(target.get(key) for key in ("provider", "profile", "model", "base_url", "auth_mode"))


def validate_arguments(schema: dict, raw: str) -> dict:
    from jsonschema import Draft202012Validator
    if not isinstance(raw, str) or len(raw) > 16000:
        raise ValueError("invalid_arguments")
    def finite(value):
        raise ValueError("nonfinite_arguments")
    try:
        value = json.loads(raw, parse_constant=finite)
    except ValueError:
        raise ValueError("invalid_read_arguments") from None
    if not isinstance(value, dict):
        raise ValueError("arguments_must_be_object")
    # Even legacy read schemas must reject undeclared fields before dispatch.
    properties = schema.get("properties", {})
    if set(value) - set(properties):
        raise ValueError("unknown_arguments")
    if not Draft202012Validator(schema).is_valid(value):
        raise ValueError("invalid_read_arguments")
    return value


def stop_worker(process) -> None:
    """Only terminate the process tree created for this Turn, including SDK startup."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
                       creationflags=subprocess.CREATE_NO_WINDOW, check=False)
    else:
        import signal
        os.killpg(process.pid, signal.SIGKILL)
    if process.poll() is None:
        process.kill()
    process.wait(timeout=5)
