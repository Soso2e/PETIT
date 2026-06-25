"""The agent loop: intent understanding + tool execution.

Flow (per Concept.md section 7):
  user message -> LLM decides intent -> may emit tool_calls -> we run tools ->
  feed results back -> LLM produces a natural-language reply.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from . import config, tools
from .lmstudio_client import chat_completion

SYSTEM_PROMPT = """あなたは「PETIT」という名前の、ユーザー専用のパーソナルAIアシスタントです。

役割:
- ユーザーの発話から意図を読み取り、必要なときだけ用意されたツールを使う。
- 単なる情報の羅列ではなく、必要に応じて「今やる1個」「次にやる1個」「後で見ればよいもの」に整理して返す。
- ユーザーを管理するのではなく、横にいる補助輪のように、自然に・簡潔に支える。

記憶について:
- あなたは会話を通じてユーザーの情報（好み・作業中の内容・決定事項）を蓄積していく。
- 過去の話題・作業・約束を思い出す必要があるときは search_memory で検索する。
- 「これ覚えておいて」と言われたら save_memory、「ここまでの話まとめて」と言われたら summarize_now を使う。
- なお会話は数時間おきに自動でまとめて記憶に蓄積されるため、毎回手動保存しなくてよい。

ルール:
- 雑談や挨拶にはツールを使わず自然に応答する。
- タスク・予定・記憶に関する具体的な要求があるときだけツールを呼ぶ。
- ツールの結果は日本語で分かりやすく要約して伝える。
- 分からないことは正直に伝える。
"""


def _build_messages(user_message: str, history: list[dict[str, str]] | None) -> list[dict[str, Any]]:
    today = date.today().isoformat()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT + f"\n\n今日の日付: {today}"},
    ]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})
    return messages


def run(user_message: str, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """Run one turn. Returns {reply, used_tools}.

    May raise LMStudioError if the model backend is unreachable; the caller
    is expected to translate that into a friendly response.
    """
    messages = _build_messages(user_message, history)
    tool_schema = tools.openai_tools_schema()
    used_tools: list[dict[str, Any]] = []

    for _ in range(config.MAX_TOOL_ITERATIONS):
        message = chat_completion(messages, tools=tool_schema)
        tool_calls = message.get("tool_calls") or []

        if not tool_calls:
            return {"reply": (message.get("content") or "").strip(), "used_tools": used_tools}

        # Record the assistant's tool-call turn, then execute each call.
        messages.append(message)
        for call in tool_calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            args = fn.get("arguments", "{}")
            result = tools.dispatch(name, args)
            used_tools.append({"name": name, "arguments": args})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id", name),
                    "name": name,
                    "content": result,
                }
            )

    # Ran out of iterations: ask the model for a final answer without tools.
    final = chat_completion(messages, tools=None)
    return {"reply": (final.get("content") or "").strip(), "used_tools": used_tools}
