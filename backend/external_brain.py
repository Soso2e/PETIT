"""Core Tool bridge for externally owned Agent loops (no second loop)."""
from __future__ import annotations

import json
from uuid import uuid4
from . import conversation_store as store, db, tools


def tool_bridge(request_id: str, target: dict, used: list):
    from . import brain
    catalog = {x["function"]["name"]: x["function"] for x in brain.schemas()}
    def petit_read_tool(name: str, arguments_json: str) -> str:
        """Call a PETIT catalog Tool. Core alone validates and approves any write."""
        from . import provider_runtime, request_context
        row = store.load_turn(request_id)
        if row["cancel_requested"]:
            raise brain.TurnCancelled("取消要求を受け付けました。")
        current = brain.check_provider(store.thread(row["thread_id"]))
        if provider_runtime.provider_identity(current) != provider_runtime.provider_identity(target):
            raise ValueError("provider_changed")
        if store.approvals(request_id):
            return store.encode({"status": "awaiting_user_approval", "stop": True})
        try:
            if (not request_context.current_is_admin() or name not in catalog
                    or name not in {x["function"]["name"] for x in brain.schemas()}
                    or name not in tools.registered_names() or len(used) >= brain.MAX_CALLS):
                raise ValueError("tool_not_allowed_or_limit")
            arguments = tools.parse_arguments(name, provider_runtime.validate_arguments(catalog[name]["parameters"], arguments_json))
        except (ValueError, TypeError):
            with db.get_connection() as c:
                store.event(c, row["thread_id"], request_id, "external_tool_rejected", {"tool": name if name in catalog else "unknown", "reason": "invalid_catalog_arguments"})
            raise
        call = {"id": "ext-" + uuid4().hex, "type": "function",
                "function": {"name": name, "arguments": store.encode(arguments)}}
        # Every attempted Tool is durable, including reads. Runtime failover must not replay a loop.
        with db.get_connection() as c:
            store.event(c, row["thread_id"], request_id, "external_tool_started", {"tool": name})
        with request_context.bind(request_id=request_id, session_id=row["thread_id"], is_admin=True):
            if tools.requires_confirmation(name):
                store.propose(request_id, call, arguments)
                raw = store.encode({"status": "awaiting_user_approval", "stop": True})
            else:
                raw = brain.execute(request_id, call, arguments)
        used.append({"name": name, "arguments": store.encode(arguments)})
        messages = json.loads(store.load_turn(request_id)["messages_json"] or "[]")
        messages.extend([{"role": "assistant", "content": "", "tool_calls": [call]},
                         {"role": "tool", "tool_call_id": call["id"], "content": brain.compact(raw, name)}])
        store.save_messages(request_id, messages)
        return brain.compact(raw, name)
    return petit_read_tool


def context(request_id: str, messages=None) -> tuple[str, str]:
    from . import brain, service_sync, time_context, dialogue_state
    from .petit_prompt import CORE_SYSTEM_PROMPT, voice_turn_instructions
    row = store.load_turn(request_id)
    instructions = (CORE_SYSTEM_PROMPT + voice_turn_instructions() + brain.INSTRUCTIONS +
                    "\n実際に呼べるTool名はpetit_read_toolだけ。下のカタログ名を直接Toolとして呼んではいけない。"
                    "petit_read_toolのname引数にカタログ名、arguments_json引数にその引数のJSON文字列を渡す。"
                    "\n承認待ちToolが返されたら直ちに回答を終了し、実行済みと説明しない。" +
                    "\n運用アラートはCoreが末尾に表示するので本文に重ねて書かない。未解決の事実: " + service_sync.warning() +
                    "\npetit_read_toolで呼べるカタログ:\n" + store.encode(brain.schemas()))
    # Approval resume has consumed input_json; the original request remains in conversations.
    if messages is None:
        payload = json.loads(row["input_json"] or "{}")
        transcript = store.history(row["thread_id"])
        current_request = payload.get("message", "")
    else:
        transcript = messages
        current_request = "上記の保存済みTool結果と承認結果を踏まえて、今回の依頼の回答を続けてください。実行済みの操作を再実行しないでください。"
    reference = store.encode({"current_time": time_context.current_datetime().isoformat(), "past_transcript": transcript,
                              "confirmed_focus": dialogue_state.load(row["thread_id"]).get("focus_stack", [])[-3:]})
    return instructions, "参考データ（過去の発話を新しい依頼として実行しない）:\n" + reference + "\n\n今回のユーザーの依頼:\n" + current_request


def finish(request_id: str, reply: str, used: list, metadata: dict):
    waiting = bool(store.approvals(request_id))
    return store.finish(request_id, {"reply": reply, "used_tools": used, "model_route": metadata},
                        status="waiting_approval" if waiting else "completed")
