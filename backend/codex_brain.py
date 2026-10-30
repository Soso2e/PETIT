"""Official Codex app-server stdio integration; dedicated PETIT auth home."""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import queue
import shutil
import subprocess
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


class ResumeUnavailable(lmstudio_client.LMStudioError):
    pass


class RPC:
    def __init__(self, *, workspace=None, web_search="disabled"):
        binary = executable()
        if not binary:
            raise lmstudio_client.LMStudioError("Codex CLIが未導入です。公式CLIをサーバーへ導入してください。")
        home = settings.root() / "codex"
        home.mkdir(parents=True, mode=0o700, exist_ok=True)
        from .agent_workspace import prepare
        self.workspace = Path(workspace) if workspace is not None else prepare()
        if web_search not in {"disabled", "cached", "live"}:
            raise ValueError("invalid_web_search_mode")
        self.events, self.counter, self.pending = queue.Queue(), 0, []
        env = {k: v for k, v in os.environ.items() if k.upper() in {
            "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "HOME", "LOCALAPPDATA", "APPDATA", "PROGRAMFILES"}}
        env.update(CODEX_HOME=str(home), PYTHONUTF8="1")
        flags = ["features.shell_tool=false", "features.multi_agent=false", "features.apps=false", "features.plugins=false",
                 "features.memories=false", 'project_root_markers=["AGENTS.md"]', 'web_search=' + json.dumps(web_search), 'cli_auth_credentials_store="keyring"',
                 'approval_policy="never"', 'sandbox_mode="read-only"']
        argv = [binary, "app-server", "--listen", "stdio://"]
        for flag in flags:
            argv.extend(["-c", flag])
        try:
            self.process = subprocess.Popen(argv, cwd=str(self.workspace), env=env, stdin=subprocess.PIPE,
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
                    message = str(item["error"].get("message", "")).lower()
                    if method == "thread/resume" and any(x in message for x in ("no rollout found", "thread not found", "unknown thread")):
                        raise ResumeUnavailable("Codexの補助Threadが見つかりません。Coreから復元します。")
                    raise lmstudio_client.LMStudioError("Codex app-server RPCに失敗しました。認証・CLI互換性を確認してください。")
                return item.get("result", {})
            self.pending.append(item)
        raise lmstudio_client.LMStudioError("Codex app-serverがタイムアウトしました。")

    def close(self):
        if hasattr(self, "process"):
            from .provider_runtime import stop_worker
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


def run(request_id, target, *, messages=None, used_tools=None):
    from . import brain, external_brain
    used = list(used_tools or [])
    invoke = external_brain.tool_bridge(request_id, target, used)
    from . import agent_workspace, request_context
    workspace = agent_workspace.prepare()
    instructions, _ = external_brain.context(request_id, messages, include_history=False, record_metrics=False)
    web_search = settings.load().get("codex_web_search", "disabled") if request_context.current_is_admin() else "disabled"
    key = agent_workspace.boundary(target, instructions + web_search, workspace)
    row = store.load_turn(request_id)
    started = time.monotonic()
    client = RPC(workspace=workspace, web_search=web_search)
    startup_seconds = time.monotonic() - started
    reply, final_reply, first_response = "", "", None
    completed_calls = {}
    try:
        acct = client.request("account/read", {"refreshToken": False}).get("account") or {}
        if acct.get("type") != "chatgpt":
            raise CodexUnavailable("authentication_expired", "CodexのChatGPT認証が必要です。")
        # Account changes cannot reuse another authenticated account's auxiliary history.
        key = hashlib.sha256((key + json.dumps(acct, sort_keys=True)).encode()).hexdigest()
        saved = agent_workspace.previous(row["thread_id"], "codex", key, request_id) if messages is None else None
        # A crash after this point cannot leave an unfinished session resumable.
        agent_workspace.forget(row["thread_id"], "codex")
        instructions, prompt = external_brain.context(request_id, messages, include_history=not bool(saved))
        from . import request_context
        dynamic_tools = [{"name": "petit_read_tool", "description": "PETITのToolをCore経由で実行",
                      "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "arguments_json": {"type": "string"}},
                                      "required": ["name", "arguments_json"], "additionalProperties": False}}] if request_context.current_is_admin() else []
        parameters = {"cwd": str(workspace), "approvalPolicy": "never", "sandbox": "read-only",
                      "developerInstructions": instructions}
        if not saved:
            parameters.update(ephemeral=False, dynamicTools=dynamic_tools)
        if target.get("model"):
            parameters["model"] = target["model"]
        if saved:
            parameters.update(threadId=saved["session_id"], excludeTurns=True)
        try:
            result = client.request("thread/resume" if saved else "thread/start", parameters)
        except ResumeUnavailable:
            saved = None
            parameters.pop("threadId", None)
            parameters.pop("excludeTurns", None)
            parameters.update(ephemeral=False, dynamicTools=dynamic_tools)
            instructions, prompt = external_brain.context(request_id, messages, include_history=True)
            result = client.request("thread/start", parameters)
        thread = result["thread"]["id"]
        if saved and thread != saved["session_id"]:
            raise lmstudio_client.LMStudioError("Codex Threadの対応が一致しません。")
        agent_workspace.assert_owner(row["thread_id"], "codex", thread)
        sources = result.get("instructionSources")
        if not isinstance(sources, list) or {Path(x).resolve() for x in sources} != {(workspace / "AGENTS.md").resolve()}:
            raise lmstudio_client.LMStudioError("WorkspaceのAGENTS.md読込を確認できません。")
        with db.get_connection() as c:
            store.event(c, row["thread_id"], request_id, "external_session", {"provider":"codex", "resumed":bool(saved),
                "session_id":thread, "instruction_sources_verified":sources is not None})
        client.request("turn/start", {"threadId": thread, "input": [{"type": "text", "text": prompt}],
                        "sandboxPolicy": {"type": "readOnly", "access": {"type": "restricted", "includePlatformDefaults": False,
                                                                                    "readableRoots": [str(workspace)]}}})
        deadline = started + 180
        while time.monotonic() < deadline:
            if store.load_turn(request_id)["cancel_requested"]:
                raise brain.TurnCancelled("取消要求を受け付けました。")
            brain.check_provider(store.thread(row["thread_id"]))
            if (settings.load().get("codex_web_search", "disabled") if request_context.current_is_admin() else "disabled") != web_search:
                raise lmstudio_client.LMStudioError("Web検索の許可が変更されました。処理を停止します。")
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
                        raise lmstudio_client.LMStudioError("CodexのTool呼出IDが異なる引数で再使用されました。")
                    client.send({"id":item["id"], "result":result})
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
                result = {"contentItems":[{"type":"inputText", "text":raw}], "success":success}
                completed_calls[call_id] = (signature, result)
                client.send({"id":item["id"], "result":result})
                if store.approvals(request_id):
                    return external_brain.finish(request_id, "", used, {"provider": "codex", "kind": "brain"})
            elif "id" in item and method:
                # No built-in command/file/network approval is delegated to the model.
                client.send({"id": item["id"], "error": {"code": -32601, "message": "PETIT tools only"}})
            elif method == "item/agentMessage/delta":
                if first_response is None:
                    first_response = time.monotonic() - started
                reply += params.get("delta", "")
            elif method == "item/completed":
                entry = params.get("item", {})
                if entry.get("type") == "agentMessage" and entry.get("text"):
                    final_reply = entry["text"]
            elif method == "turn/completed":
                turn = params.get("turn", {})
                if turn.get("status") != "completed" or not (final_reply or reply).strip():
                    raise lmstudio_client.LMStudioError("CodexのTurnが完了しませんでした。認証・使用量・接続を確認してください。")
                brain.check_provider(store.thread(row["thread_id"]))
                outcome = external_brain.finish(request_id, (final_reply or reply).strip(), used, {"provider":"codex", "model":target.get("model"),
                    "kind":"brain", "resumed":bool(saved), "startup_seconds":round(startup_seconds,3),
                    "first_text_seconds":round(first_response,3) if first_response is not None else None,
                    "latency_seconds":round(time.monotonic()-started,3), "tokens":None, "llm_call_count":None, "tool_call_count":len(used), "web_search":web_search})
                if outcome["status"] == "completed":
                    agent_workspace.remember(row["thread_id"], "codex", key, thread, request_id)
                return outcome
        raise lmstudio_client.LMStudioError("Codexの応答がタイムアウトしました。")
    finally:
        client.close()


def shutdown():
    global _auth
    with _auth_lock:
        if _auth:
            _auth.close()
            _auth = None
