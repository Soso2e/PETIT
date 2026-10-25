"""Official SDK backend: one SDK agent loop, PETIT-owned history and reads.

No consumer CLI wrapper, OAuth reuse, automatic provider fallback, or SDK writes.
"""
from __future__ import annotations

import asyncio
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from . import conversation_store as store, db, lmstudio_client, request_context, tools

SDK_VERSION = "0.1.22"
READ_TOOLS = frozenset({"get_current_time", "get_tasks", "get_schedule", "get_work_status",
                        "get_project_status", "find_projects", "get_reminders"})


def installed() -> bool:
    try:
        return importlib.metadata.version("google-antigravity") == SDK_VERSION
    except importlib.metadata.PackageNotFoundError:
        return False


def read_catalog() -> list[dict]:
    return [item for item in tools.openai_tools_schema()
            if item["function"]["name"] in READ_TOOLS
            and tools.risk_for(item["function"]["name"]) == "safe_read"]


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


def diagnostic(request_id: str, data: dict) -> None:
    row = store.load_turn(request_id)
    with db.get_connection() as connection:
        store.event(connection, row["thread_id"], request_id, "model_backend", data)


def bridge(request_id: str, target: dict, used: list):
    """Only this read-only callable is exposed to the SDK's custom-tool runner."""
    catalog = {item["function"]["name"]: item["function"] for item in read_catalog()}

    def petit_read_tool(name: str, arguments_json: str) -> str:
        """Read a PETIT fact. Use an exact catalog name and its JSON arguments. Writes are unavailable."""
        from . import brain
        row = store.load_turn(request_id)
        if row["cancel_requested"]:
            raise brain.TurnCancelled("取消要求を受け付けました。")
        current = brain.check_provider(store.thread(row["thread_id"]))
        if provider_identity(current) != provider_identity(target):
            raise ValueError("provider_changed")
        # Recheck the live registry, not just the startup catalog.
        if name not in catalog or name not in READ_TOOLS or tools.risk_for(name) != "safe_read":
            raise ValueError("read_tool_not_allowed")
        if len(used) >= 12:
            raise ValueError("read_tool_limit")
        arguments = tools.parse_arguments(name, validate_arguments(catalog[name]["parameters"], arguments_json))
        used.append({"name": name, "arguments": store.encode(arguments)})
        with request_context.bind(request_id=request_id, session_id=row["thread_id"]):
            raw = brain.execute(request_id, {"id": "agy-" + uuid.uuid4().hex,
                                             "function": {"name": name}}, arguments)
        return brain.compact(raw, name)

    return petit_read_tool


def sdk_config(root: Path, target: dict, instructions: str, read_tool):
    from google.antigravity import CapabilitiesConfig, LocalAgentConfig, LocalOpenAIAgentConfig
    from google.antigravity.hooks import policy
    from google.antigravity.types import BudgetConfig, BuiltinTools
    if not installed():
        raise lmstudio_client.LMStudioError("公式Antigravity SDK 0.1.22をrequirements-antigravity.txtから導入してください。")
    options = dict(
        model=target["model"], system_instructions=instructions,
        capabilities=CapabilitiesConfig(enabled_tools=[BuiltinTools.FINISH]),
        policies=[policy.deny("*"), policy.allow("finish"), policy.allow("petit_read_tool")],
        tools=[read_tool], mcp_servers=[], skills_paths=[], inline_skills=[], subagents=[], triggers=[],
        workspaces=[str(root / "workspace")], app_data_dir=str(root / "app"),
        save_dir=str(root / "sessions"), budget_config=BudgetConfig(max_model_calls=8, max_tool_calls=12, max_output_tokens=4096),
    )
    if target["auth_mode"] == "local":
        return LocalOpenAIAgentConfig(base_url=target["base_url"], **options)
    return LocalAgentConfig(api_key=target["api_key"], vertex=False, **options)


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


def run_isolated(request_id: str, target: dict, instructions: str, prompt: str,
                 used: list, metadata: dict) -> str:
    """Parent owns a hard deadline and cancellation even during SDK __aenter__."""
    from . import brain, model_routing, config
    payload = store.encode({"request_id": request_id, "target": target, "instructions": instructions,
                            "prompt": prompt, "db_path": str(config.DB_PATH),
                            "routing_path": str(model_routing.STATE_PATH)})
    options = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    process = subprocess.Popen([sys.executable, "-m", "backend.antigravity_worker"],
                               cwd=str(Path(__file__).resolve().parents[1]), stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding="utf-8",
                               env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}, **options)
    output = []
    def communicate():
        output.append(process.communicate(payload))
    reader = threading.Thread(target=communicate, daemon=True, name="petit-sdk-output")
    reader.start()
    deadline = time.monotonic() + target.get("timeout_seconds", 90)
    try:
        while process.poll() is None:
            row = store.load_turn(request_id)
            if row["cancel_requested"]:
                raise brain.TurnCancelled("取消要求を受け付けました。")
            if time.monotonic() >= deadline:
                raise TimeoutError()
            current = brain.check_provider(store.thread(row["thread_id"]))
            if provider_identity(current) != provider_identity(target):
                raise lmstudio_client.LMStudioError("実行中にProvider設定が変更されました。自動再送しません。")
            reader.join(.1)
        reader.join(5)
        if not output or process.returncode != 0:
            raise lmstudio_client.LMStudioError("Antigravity SDK Workerが終了しました。接続・モデル・依存を確認してください。")
        result = json.loads(output[0][0])
        if not result.get("ok"):
            metadata["sdk_error_type"] = str(result.get("error_type", "unknown"))[:80]
            raise lmstudio_client.LMStudioError("Antigravity SDKが返答を生成できませんでした。診断と接続設定を確認してください。")
        used.extend(result["used_tools"])
        metadata.update(result["metadata"])
        return result["reply"]
    finally:
        stop_worker(process)
        reader.join(5)


async def execute_sdk(request_id: str, target: dict, instructions: str, prompt: str,
                      used: list, metadata: dict) -> str:
    from google.antigravity import Agent
    from . import brain
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="petit-antigravity-turn-") as temp:
        root = Path(temp)
        for name in ("workspace", "app", "sessions"):
            (root / name).mkdir()
        cfg = sdk_config(root, target, instructions, bridge(request_id, target, used))
        async with asyncio.timeout(target.get("timeout_seconds", 90)):
            async with Agent(cfg) as agent:
                metadata["runtime_startup_seconds"] = round(time.monotonic() - started, 3)
                response = None
                async def consume():
                    nonlocal response
                    response = await agent.chat(prompt)
                    metadata["sdk_conversation_id"] = agent.conversation_id
                    return await response.text()
                task = asyncio.create_task(consume())
                try:
                    while not task.done():
                        await asyncio.wait({task}, timeout=.15)
                        if store.load_turn(request_id)["cancel_requested"]:
                            raise brain.TurnCancelled("取消要求を受け付けました。")
                        current = brain.check_provider(store.thread(store.load_turn(request_id)["thread_id"]))
                        if provider_identity(current) != provider_identity(target):
                            raise lmstudio_client.LMStudioError("実行中にProvider設定が変更されました。自動再送しません。")
                    text = await task
                    metadata["sdk_conversation_id"] = agent.conversation_id
                    usage = response.usage_metadata
                    metadata["usage"] = usage.model_dump() if usage is not None else None
                    stop = getattr(response.stop_reason, "value", str(response.stop_reason))
                    if stop != "UNSPECIFIED":
                        raise lmstudio_client.LMStudioError("Antigravity SDKが上限またはquotaで中断しました。自動再送しません。")
                    if not text.strip():
                        raise lmstudio_client.LMStudioError("Antigravity SDKから返答を取得できませんでした。")
                    return text.strip()
                finally:
                    if not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)


def run(request_id: str, target: dict) -> dict:
    from . import brain, time_context
    from .petit_prompt import CORE_SYSTEM_PROMPT, voice_turn_instructions
    if not target.get("configured"):
        raise lmstudio_client.LMStudioError("Antigravity SDKの依存・モデル・認証設定を確認してください。")
    row = store.load_turn(request_id)
    if row["cancel_requested"]:
        raise brain.TurnCancelled("取消要求を受け付けました。")
    payload = json.loads(row["input_json"])
    instructions = (CORE_SYSTEM_PROMPT + voice_turn_instructions() + brain.INSTRUCTIONS +
                    "\nこのバックエンドはRead専用。書込やOS操作はできない。利用可能なToolがなければできないと伝える。"
                    "\npetit_read_toolで使えるカタログ:\n" + store.encode(read_catalog()))
    # Core remains canonical. Fresh SDK state receives only the bounded same-thread transcript.
    prompt = store.encode({"current_time": time_context.current_datetime().isoformat(timespec="seconds"),
                           "history": store.history(row["thread_id"]), "user_message": payload["message"]})
    used = []
    metadata = {"kind": "brain", "provider": "antigravity_sdk", "sdk_version": SDK_VERSION,
                "model": target["model"], "auth_mode": target["auth_mode"],
                "inference_provider": "lm_studio" if target["auth_mode"] == "local" else "gemini_api",
                "local": target["auth_mode"] == "local", "usage": None,
                "sdk_conversation_id": None, "fallback": False}
    started = time.monotonic()
    diagnostic(request_id, {**metadata, "state": "started"})
    try:
        reply = run_isolated(request_id, target, instructions, prompt, used, metadata)
        if store.load_turn(request_id)["cancel_requested"]:
            raise brain.TurnCancelled("取消要求を受け付けました。")
    except BaseException as exc:
        metadata["latency_seconds"] = round(time.monotonic() - started, 3)
        diagnostic(request_id, {**metadata, "state": "interrupted" if isinstance(exc, brain.TurnCancelled) else "failed",
                                "error_type": type(exc).__name__})
        if isinstance(exc, (brain.TurnCancelled, lmstudio_client.LMStudioError)):
            raise
        if isinstance(exc, TimeoutError):
            raise lmstudio_client.LMStudioError("Antigravity SDKがタイムアウトしました。自動再送していません。") from None
        raise lmstudio_client.LMStudioError("Antigravity SDKを実行できませんでした。依存・接続・モデルを確認してください。") from None
    metadata["latency_seconds"] = round(time.monotonic() - started, 3)
    diagnostic(request_id, {**metadata, "state": "completed"})
    return store.finish(request_id, {"reply": reply, "used_tools": used, "model_route": metadata})
