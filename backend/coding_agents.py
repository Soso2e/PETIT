"""CLI development agents use only the Job-scoped Core file/check catalog."""
import json
import queue
import time

from . import antigravity_cli_brain, codex_brain, lmstudio_client

CATALOG = [{"type": "function", "function": {"name": name, "description": description, "parameters": schema}}
    for name, description, schema in [
        ("list_files", "List source files in this job's isolated repository copy.",
         {"type": "object", "properties": {}, "additionalProperties": False}),
        ("read_file", "Read a UTF-8 source file and its SHA-256. Read applicable AGENTS.md before edits.",
         {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False}),
        ("write_file", "Write a source file. expected_sha256 must match the last read; empty string creates a new file.",
         {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"},
            "expected_sha256": {"type": "string"}}, "required": ["path", "content", "expected_sha256"], "additionalProperties": False}),
        ("run_static_checks", "Run syntax and whitespace checks. This does not execute tests or user code.",
         {"type": "object", "properties": {}, "additionalProperties": False})]]

INSTRUCTIONS = """You are an approved PETIT local development job. Work only through the supplied tools.
Read AGENTS.md, relevant README/Concept/PROGRESS and applicable nested instructions before editing.
Use list_files/read_file to investigate, make the smallest changes, then run_static_checks.
No shell, deletion, dependency installation, push, PR or merge is available.
The original checkout is unchanged; edits are in a separate clone from the approved commit.
Report in Japanese what changed, static check results, and tests/host behavior that remain unverified.
Do not claim tests passed: only static checks are available. Never mark the user's task completed yourself.
"""


def run(provider, target, goal, invoke, check, progress):
    messages = [{"role": "system", "content": INSTRUCTIONS}, {"role": "user", "content": goal}]
    if provider == "antigravity_cli":
        for _ in range(32):
            check()
            progress("model_request")
            response, metadata = antigravity_cli_brain.completion(target, messages, CATALOG, check)
            progress("model_response")
            calls = response.get("tool_calls") or []
            if not calls:
                if not response["content"].strip():
                    raise ValueError("empty_agent_reply")
                return response["content"]
            messages.append(response)
            for call in calls:
                check()
                function = call["function"]
                raw = invoke(function["name"], json.loads(function["arguments"]))
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(raw, ensure_ascii=False)})
        raise ValueError("coding_agent_step_limit")
    client = codex_brain.RPC()
    reply, final = "", ""
    seen = {}
    try:
        if (client.request("account/read", {"refreshToken": False}).get("account") or {}).get("type") != "chatgpt":
            raise codex_brain.CodexUnavailable("authentication_required", "CodexのChatGPT認証が必要です。")
        params = {"cwd": client.temp.name, "sandbox": "read-only", "approvalPolicy": "never", "ephemeral": True,
            "baseInstructions": INSTRUCTIONS + "\nUse petit_coding_tool with a catalog name and JSON arguments: " + json.dumps(CATALOG),
            "dynamicTools": [{"name": "petit_coding_tool", "description": "Job-scoped PETIT coding tools",
                "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "arguments_json": {"type": "string"}},
                    "required": ["name", "arguments_json"], "additionalProperties": False}}]}
        if target.get("model"):params["model"] = target["model"]
        thread = client.request("thread/start", params)["thread"]["id"]
        progress("model_request")
        client.request("turn/start", {"threadId": thread, "input": [{"type": "text", "text": goal}],
            "sandboxPolicy": {"type": "readOnly", "access": {"type": "restricted", "includePlatformDefaults": False,
                "readableRoots": [client.temp.name]}}})
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            check()
            try:item = client.pending.pop(0) if client.pending else client.events.get(timeout=.2)
            except queue.Empty:continue
            if item.get("_closed"):raise ValueError("codex_disconnected")
            method, params = item.get("method"), item.get("params", {})
            if method == "item/tool/call":
                key = params.get("callId", item["id"])
                signature = json.dumps(params, sort_keys=True)
                if key in seen:
                    if seen[key][0] != signature:raise ValueError("reused_tool_id")
                    result = seen[key][1]
                else:
                    if params.get("tool") != "petit_coding_tool" or params.get("threadId", thread) != thread:
                        raise ValueError("invalid_coding_tool")
                    args = params["arguments"]
                    if isinstance(args, str):args = json.loads(args)
                    raw = invoke(args["name"], json.loads(args["arguments_json"]))
                    result = {"contentItems": [{"type": "inputText", "text": json.dumps(raw, ensure_ascii=False)}], "success": not bool(raw.get("error"))}
                    seen[key] = (signature, result)
                client.send({"id": item["id"], "result": result})
            elif method and "id" in item:
                client.send({"id": item["id"], "error": {"code": -32601, "message": "PETIT coding tools only"}})
            elif method == "item/agentMessage/delta":reply += params.get("delta", "")
            elif method == "item/completed" and params.get("item", {}).get("type") == "agentMessage":
                if params["item"].get("phase") in (None, "final_answer"):final = params["item"].get("text", "")
            elif method == "turn/completed":
                if params.get("turn", {}).get("status") != "completed" or not (final or reply).strip():
                    raise ValueError("codex_turn_failed")
                return (final or reply).strip()
        raise ValueError("coding_agent_timeout")
    finally:client.close()
