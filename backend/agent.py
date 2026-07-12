"""The agent loop: intent understanding + tool execution.

Flow (per Concept.md section 7):
  user message -> LLM decides intent -> may emit tool_calls -> we run tools ->
  feed results back -> LLM produces a natural-language reply.
"""
from __future__ import annotations

from datetime import date
import json
from typing import Any

from . import config, db, model_router, recall, situation, tools
from .lmstudio_client import LMStudioError, chat_completion

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
- さらに過去を思い出す必要があるときは search_memory で検索する。search_memory は会話記憶だけでなく、設定済みの Obsidian vault も検索対象に含む。
- 「これ覚えておいて」なら save_memory、「ここまでの話まとめて」なら summarize_now を使う。
- 会話は数時間おきに自動でまとまるため、毎回手動保存しなくてよい。

タスク・復帰:
- 「○○をタスクにして」「明日○○やる」なら create_task を使う。分類が明らかなら Category を入れる。
  分類が曖昧でユーザーが分類を重視していそうなら、無理に決めず短く確認する。
- 「終わった」「完了にして」なら complete_task を使う。対象が曖昧なら候補を確認する。
- 「ここまで引き継ぎ」「中断する」「明日再開できるように」なら create_handoff_note を使う。
- 「どこまでやったっけ」「続きに戻りたい」「復帰したい」なら restore_context を使う。

ルール:
- 明示されなくても、回答がユーザーの状況・過去の判断・進行中プロジェクトに依存するなら、BRAIN・タスク・予定を確認する。
- 単純な雑談には不要なツールを使わない。ただし朝の挨拶や「何をすればいい？」は状況確認が必要な相談として扱う。
- 会話から未記録の約束、期限、決定、次の行動を見つけたら、勝手に書き込まず「タスク／記録にする？」と短く提案する。
- カレンダー、Notion、メールなど外部サービスへの追加・更新・削除は、ユーザーの明示的な確認後にだけ行う。
- ツール・長文・複数段階の判断はエージェントモデル、短い会話は会話モデルで処理される。
- 「今何時？」「今日何日？」「今の時間」のように現在時刻・日付を聞かれたら get_current_time を使う。
- 天気やニュースをすぐ答えるときは get_weather / search_news を使う。
- 「調べておいて」「分かったら教えて」「会話を続けながら調べたい」意図なら start_background_research を使い、まず短く受け付けたことを返す。
- ツールの結果は日本語で分かりやすく、会話の流れで伝える。
- 分からないことは正直に、でも相棒らしく伝える。
"""


def _build_messages(
    user_message: str,
    history: list[dict[str, str]] | None,
    *,
    include_context: bool = True,
) -> list[dict[str, Any]]:
    today = date.today().isoformat()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT + f"\n\n今日の日付: {today}"},
    ]
    if include_context:
        # Agent turns can spend time collecting context. Simple chat stays fast.
        recall_block = recall.build_recall_block(user_message)
        situation_block = situation.build_context_block(user_message)
        if situation_block:
            messages.append({"role": "system", "content": situation_block})
        if recall_block:
            messages.append({"role": "system", "content": recall_block})
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})
    return messages


def _present_agent_reply(reply: str, route: dict[str, Any]) -> str:
    """Let the chat model present agent output without changing its substance."""
    if not reply or route["kind"] != "agent" or config.CHAT_MODEL == route["model"]:
        return reply
    try:
        message = chat_completion(
            [
                {
                    "role": "system",
                    "content": (
                        "あなたはPETITの会話・つなぎ担当。エージェントの回答を自然で読みやすい日本語に整える。"
                        "事実、数値、警告、未確認事項、次の行動は削除・変更しない。新しい事実を足さない。"
                    ),
                },
                {"role": "user", "content": reply},
            ],
            tools=None,
            model=config.CHAT_MODEL,
            temperature=0.5,
        )
    except LMStudioError:
        return reply
    presented = (message.get("content") or "").strip()
    if presented:
        route["presented_by"] = config.CHAT_MODEL
        return presented
    return reply


def _quick_deferred_reply(user_message: str, history: list[dict[str, str]] | None) -> str:
    message = chat_completion(
        [
            {
                "role": "system",
                "content": (
                    "あなたはPETITの軽量会話担当。ユーザーの相談にまず短く返す。"
                    "詳しい確認はバックグラウンドで続く前提で、1〜2文だけ返す。"
                    "未確認の事実やデータは断定しない。"
                ),
            },
            *(history or [])[-6:],
            {"role": "user", "content": user_message},
        ],
        tools=None,
        model=config.CHAT_MODEL,
        temperature=0.6,
    )
    reply = (message.get("content") or "").strip()
    return reply or "先に短く返すね。詳しい確認は裏で続けて、分かったら追加で出す。"


def _build_tool_result_message(user_message: str, results: list[dict[str, str]]) -> dict[str, str]:
    lines = [
        "以下は、元のユーザー発話に対してPython側で実行したツール結果です。",
        f"元のユーザー発話: {user_message}",
        "この結果を使って、ユーザーへ自然な日本語で返答してください。",
    ]
    for item in results:
        lines.extend(
            [
                "",
                f"ツール: {item['name']}",
                f"引数: {item['arguments']}",
                f"結果: {item['content']}",
            ]
        )
    return {"role": "user", "content": "\n".join(lines)}


def _queue_agent_followup(user_message: str, history: list[dict[str, str]] | None) -> int:
    payload = {"message": user_message, "history": history or []}
    return db.create_job("agent_followup", json.dumps(payload, ensure_ascii=False))


def run(
    user_message: str,
    history: list[dict[str, str]] | None = None,
    *,
    allow_defer: bool = True,
) -> dict[str, Any]:
    """Run one turn. Returns {reply, used_tools}.

    May raise LMStudioError if the model backend is unreachable; the caller
    is expected to translate that into a friendly response.
    """
    route = model_router.choose(user_message, history)
    if config.DEFER_AGENT_JOBS and allow_defer and model_router.can_defer(user_message, route):
        job_id = _queue_agent_followup(user_message, history)
        quick_reply = _quick_deferred_reply(user_message, history)
        return {
            "reply": quick_reply,
            "used_tools": [{"name": "agent_followup", "arguments": json.dumps({"job_id": job_id})}],
            "model_route": {
                **route,
                "deferred": True,
                "job_id": job_id,
                "presented_by": config.CHAT_MODEL,
            },
        }

    messages = _build_messages(user_message, history, include_context=route["kind"] == "agent")
    tool_schema = tools.openai_tools_schema()
    active_tools = tool_schema if route["kind"] == "agent" else None
    used_tools: list[dict[str, Any]] = []

    for _ in range(config.MAX_TOOL_ITERATIONS):
        message = chat_completion(messages, tools=active_tools, model=route["model"])
        tool_calls = message.get("tool_calls") or []

        if not tool_calls:
            reply = _present_agent_reply((message.get("content") or "").strip(), route)
            return {
                "reply": reply,
                "used_tools": used_tools,
                "model_route": route,
            }

        tool_results: list[dict[str, str]] = []
        for call in tool_calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            args = fn.get("arguments", "{}")
            result = tools.dispatch(name, args)
            used_tools.append({"name": name, "arguments": args})
            tool_results.append(
                {
                    "name": name,
                    "arguments": args,
                    "content": result,
                }
            )
        messages.append(_build_tool_result_message(user_message, tool_results))

    # Ran out of iterations: ask the model for a final answer without tools.
    final = chat_completion(messages, tools=None, model=route["model"])
    reply = _present_agent_reply((final.get("content") or "").strip(), route)
    return {
        "reply": reply,
        "used_tools": used_tools,
        "model_route": route,
    }
