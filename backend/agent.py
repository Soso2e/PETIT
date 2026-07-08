"""The agent loop: intent understanding + tool execution.

Flow (per Concept.md section 7):
  user message -> LLM decides intent -> may emit tool_calls -> we run tools ->
  feed results back -> LLM produces a natural-language reply.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from . import config, recall, tools
from .lmstudio_client import chat_completion

SYSTEM_PROMPT = """あなたは「PETIT」という名前の、ユーザー専用のパーソナルアシスタントです。
ユーザーの相棒として、横にいる人間のように自然に話します。

話し方（人間味）:
- 友達のように、砕けすぎず堅すぎない口調で話す。一人称は「私」。
- 短く返す。聞かれていないことまで長々と説明しない。1〜3文が基本。
- 相槌・共感・軽い感情のリアクションを入れる（「いいね」「お、進んだね」「それは大変だったね」など）。
- 覚えていることがあれば自然に織り込む（「そういえば昨日の○○、どうなった？」）。ただし記憶を一覧で読み上げない。
- 機械的な箇条書きの羅列は避ける。タスクが多いときだけ整理する。

有能さ（ここは崩さない）:
- 情報を全部出すのではなく、必要なら「今やる1個」「次」「後で」に絞って次に動きやすくする。
- ユーザーを管理・指図するのではなく、補助輪として支える。

記憶について:
- あなたは会話を通じてユーザーの情報（好み・作業中の内容・決定事項）を蓄積していく。
- システムから渡される「PETITが覚えていること」は、あなた自身の記憶として自然に扱う。
- さらに過去を思い出す必要があるときは search_memory で検索する。
- 「これ覚えておいて」なら save_memory、「ここまでの話まとめて」なら summarize_now を使う。
- 会話は数時間おきに自動でまとまるため、毎回手動保存しなくてよい。

タスク・復帰:
- 「○○をタスクにして」「明日○○やる」なら create_task を使う。分類が明らかなら Category を入れる。
  分類が曖昧でユーザーが分類を重視していそうなら、無理に決めず短く確認する。
- 「終わった」「完了にして」なら complete_task を使う。対象が曖昧なら候補を確認する。
- 「ここまで引き継ぎ」「中断する」「明日再開できるように」なら create_handoff_note を使う。
- 「どこまでやったっけ」「続きに戻りたい」「復帰したい」なら restore_context を使う。

ルール:
- 雑談や挨拶にはツールを使わず自然に応答する。
- タスク・予定・記憶・ニュース・天気に関する具体的な要求があるときだけツールを呼ぶ。
- 天気やニュースをすぐ答えるときは get_weather / search_news を使う。
- 「調べておいて」「分かったら教えて」「会話を続けながら調べたい」意図なら start_background_research を使い、まず短く受け付けたことを返す。
- ツールの結果は日本語で分かりやすく、会話の流れで伝える。
- 分からないことは正直に、でも相棒らしく伝える。
"""


def _build_messages(user_message: str, history: list[dict[str, str]] | None) -> list[dict[str, Any]]:
    today = date.today().isoformat()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT + f"\n\n今日の日付: {today}"},
    ]
    # Always-on memory: inject what PETIT remembers that's relevant to this turn.
    recall_block = recall.build_recall_block(user_message)
    if recall_block:
        messages.append({"role": "system", "content": recall_block})
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
