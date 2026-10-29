"""Official Codex app-server stdio integration; dedicated PETIT auth home."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import tempfile
import threading
import time

from . import setup_store as settings, conversation_store as store, lmstudio_client, db

_auth = None
_auth_lock = threading.RLock()


def executable() -> str | None:
    """Resolve once consistently for status, selection and process startup."""
    override = os.getenv("PETIT_CODEX_EXECUTABLE", "").strip()
    if override:
        path = Path(override).expanduser()
        try:
            return str(path) if path.is_absolute() and path.is_file() else None
        except OSError:
            return None
    found = shutil.which("codex")
    if found:
        return found
    # Stable official desktop launcher; never guess a versioned hash directory.
    local = os.getenv("LOCALAPPDATA")
    if os.name == "nt" and local:
        candidate = Path(local) / "OpenAI" / "Codex" / "bin" / "codex.exe"
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            pass
    return None


class CodexUnavailable(lmstudio_client.LMStudioError):
    def __init__(self, reason, message):
        self.reason = reason
        super().__init__(message)


class RPC:
    def __init__(self):
        binary = executable()
        if not binary:
            raise lmstudio_client.LMStudioError("Codex CLIが見つかりません。サーバーのPATH・標準配置先またはPETIT_CODEX_EXECUTABLEを確認してください。")
        home = settings.root() / "codex"
        home.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="petit-codex-")
        self.events, self.counter, self.pending = queue.Queue(), 0, []
        env = {k: v for k, v in os.environ.items() if k.upper() in {
            "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "HOME", "LOCALAPPDATA", "APPDATA", "PROGRAMFILES"}}
        env.update(CODEX_HOME=str(home), PYTHONUTF8="1")
        flags = ["features.shell_tool=false", "features.multi_agent=false", "features.apps=false", "features.plugins=false",
                 "features.memories=false", 'web_search="disabled"', 'cli_auth_credentials_store="keyring"',
                 'approval_policy="never"', 'sandbox_mode="read-only"']
        argv = [binary, "app-server", "--listen", "stdio://"]
        for flag in flags:
            argv.extend(["-c", flag])
        try:
            self.process = subprocess.Popen(argv, cwd=self.temp.name, env=env, stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                        **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}))
            from .cli_job import ProcessJob
            self.job = ProcessJob(self.process)
            threading.Thread(target=self._read, daemon=True).start()
            self.request("initialize", {"clientInfo": {"name": "petit", "title": "PETIT", "version": "0.34.1"},
                        "capabilities": {"experimentalApi": True}}, timeout=20)
            self.send({"method": "initialized", "params": {}})
        except BaseException:
            self.close()
            raise

    def _read(self):
        try:
            for line in self.process.stdout:
                if len(line) > 4_000_000:
                    break
                self.events.put(json.loads(line))
        except (ValueError, OSError):
            pass
        finally:
            self.events.put({"_closed": True})

    def send(self, data):
        self.process.stdin.write(json.dumps(data, ensure_ascii=True) + "\n")
        self.process.stdin.flush()

    def request(self, method, params=None, timeout=30):
        self.counter += 1
        ident = self.counter
        self.send({"id": ident, "method": method, "params": params or {}})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                item = self.events.get(timeout=min(.2, max(.001, deadline-time.monotonic())))
            except queue.Empty:
                continue
            if item.get("_closed"):
                raise lmstudio_client.LMStudioError("Codex app-serverとの接続が終了しました。")
            if item.get("id") == ident and "method" not in item:
                if item.get("error"):
                    raise lmstudio_client.LMStudioError("Codex app-server RPCに失敗しました。認証・CLI互換性を確認してください。")
                return item.get("result", {})
            self.pending.append(item)
        raise lmstudio_client.LMStudioError("Codex app-serverがタイムアウトしました。")

    def close(self):
        if hasattr(self, "process"):
            from .antigravity_brain import stop_worker
            if self.process.poll() is None:
                self.process.stdin.close()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    stop_worker(self.process)
            for stream in (self.process.stdin, self.process.stdout):
                if not stream.closed:
                    stream.close()
        if getattr(self, "job", None):
            self.job.close()
        self.temp.cleanup()


def auth_client():
    global _auth
    with _auth_lock:
        if _auth is None or _auth.process.poll() is not None:
            _auth = RPC()
        return _auth


def login():
    with _auth_lock:
        return auth_client().request("account/login/start", {"type": "chatgptDeviceCode"})


def account():
    with _auth_lock:
        data = auth_client().request("account/read", {"refreshToken": False})
        acct = data.get("account")
        return {"authenticated": bool(acct and acct.get("type") == "chatgpt"),
                "auth_mode": (acct or {}).get("type"), "plan": (acct or {}).get("planType")}


def logout():
    with _auth_lock:
        auth_client().request("account/logout")


def status():
    # Rendering settings must not start a CLI or infer login from a saved flag.
    return {"installed": bool(executable()), "transport": "cli", "protocol": "app-server/stdio",
            "authenticated": None, "inference": "unknown"}


def diagnose():
    result = status()
    if not result["installed"]:
        return {**result, "error": "Codex CLIが見つかりません。サーバーのPATH・標準配置先またはPETIT_CODEX_EXECUTABLEを確認してください。"}
    client = None
    try:
        client = RPC()
        acct = client.request("account/read", {"refreshToken": False}).get("account") or {}
        return {**result, "authenticated": acct.get("type") == "chatgpt", "auth_mode": acct.get("type"),
                "plan": acct.get("planType"), "protocol_ready": True}
    except PermissionError:
        return {**result, "error": "PETIT専用Codex設定フォルダにアクセスできません。Core実行ユーザーとフォルダ権限を確認してください。"}
    except (OSError, lmstudio_client.LMStudioError):
        return {**result, "error": "Codex CLIとの接続に失敗しました。公式CLIの導入・互換性を確認してください。"}
    finally:
        if client is not None:
            client.close()


def run(request_id, target, *, messages=None, used_tools=None):
    from . import brain, external_brain
    instructions, prompt = external_brain.context(request_id, messages)
    used = list(used_tools or [])
    invoke = external_brain.tool_bridge(request_id, target, used)
    client = RPC()
    started, reply, final_reply = time.monotonic(), "", ""
    completed_calls = {}
    try:
        acct = client.request("account/read", {"refreshToken": False}).get("account") or {}
        if acct.get("type") != "chatgpt":
            raise CodexUnavailable("authentication_expired", "CodexのChatGPT認証が必要です。")
        from . import request_context
        dynamic_tools = [{"name": "petit_read_tool", "description": "PETITのToolをCore経由で実行",
                      "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "arguments_json": {"type": "string"}},
                                      "required": ["name", "arguments_json"], "additionalProperties": False}}] if request_context.current_is_admin() else []
        parameters = {"cwd": client.temp.name, "approvalPolicy": "never", "sandbox": "read-only", "ephemeral": True,
                      "baseInstructions": instructions, "dynamicTools": dynamic_tools}
        if target.get("model"):
            parameters["model"] = target["model"]
        thread = client.request("thread/start", parameters)["thread"]["id"]
        row = store.load_turn(request_id)
        with db.get_connection() as connection:
            store.event(connection, row["thread_id"], request_id, "external_session",
                        {"provider": "codex", "transport": "cli", "session_id": thread})
        client.request("turn/start", {"threadId": thread, "input": [{"type": "text", "text": prompt}],
                        "sandboxPolicy": {"type": "readOnly", "access": {"type": "restricted", "includePlatformDefaults": False,
                                                                                    "readableRoots": [client.temp.name]}}})
        deadline = started + 180
        while time.monotonic() < deadline:
            if store.load_turn(request_id)["cancel_requested"]:
                raise brain.TurnCancelled("取消要求を受け付けました。")
            brain.check_provider(store.thread(row["thread_id"]))
            try:
                item = client.pending.pop(0) if client.pending else client.events.get(timeout=.2)
            except queue.Empty:
                continue
            if item.get("_closed"):
                raise lmstudio_client.LMStudioError("Codex接続が終了しました。")
            method, params = item.get("method"), item.get("params", {})
            if method == "item/tool/call":
                call_id = params.get("callId", item["id"])
                signature = json.dumps(params, sort_keys=True, ensure_ascii=True)
                if call_id in completed_calls:
                    previous, result = completed_calls[call_id]
                    if previous != signature:
                        raise lmstudio_client.LMStudioError("CodexのTool呼出IDが異なる引数で再使用されました。再実行しません。")
                    client.send({"id": item["id"], "result": result})
                    continue
                try:
                    if not request_context.current_is_admin() or params.get("threadId", thread) != thread or params.get("tool") != "petit_read_tool":
                        raise ValueError("tool_not_allowed")
                    args = params["arguments"]
                    if isinstance(args, str):
                        args = json.loads(args)
                    raw = invoke(args["name"], args["arguments_json"])
                    success = not brain.failed(raw)
                except (ValueError, KeyError, TypeError):
                    raw, success = '{"error":"invalid_tool_call"}', False
                result = {"contentItems": [{"type": "inputText", "text": raw}], "success": success}
                completed_calls[call_id] = (signature, result)
                client.send({"id": item["id"], "result": result})
                if store.approvals(request_id):
                    return external_brain.finish(request_id, "", used, {"provider": "codex", "kind": "brain"})
            elif "id" in item and method:
                # No built-in command/file/network approval is delegated to the model.
                client.send({"id": item["id"], "error": {"code": -32601, "message": "PETIT tools only"}})
            elif method == "item/agentMessage/delta":
                reply += params.get("delta", "")
            elif method == "item/completed" and params.get("item", {}).get("type") == "agentMessage":
                message = params["item"]
                if message.get("phase") in (None, "final_answer"):
                    final_reply = message.get("text", "")
            elif method == "turn/completed":
                turn = params.get("turn", {})
                reply = final_reply or reply
                if turn.get("status") != "completed" or not reply.strip():
                    raise lmstudio_client.LMStudioError("CodexのTurnが完了しませんでした。認証・使用量・接続を確認してください。")
                return external_brain.finish(request_id, reply.strip(), used, {"provider": "codex", "model": target.get("model"),
                        "kind": "brain", "transport": "cli", "latency_seconds": round(time.monotonic()-started, 3)})
        raise lmstudio_client.LMStudioError("Codexの応答がタイムアウトしました。")
    finally:
        client.close()


def shutdown():
    global _auth
    with _auth_lock:
        if _auth:
            _auth.close()
            _auth = None
