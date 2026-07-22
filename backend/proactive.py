"""Proactive openers — PETIT が向こうから話しかける層。

「生きてる感」を出すために、ユーザーがアプリを開いたとき等に PETIT 側から
一言を生成する。時間帯・直近のエピソード・作業中の内容を踏まえた自然な切り出し。

完全なサーバープッシュ（アプリを閉じていても届く）には OS 通知や常駐が要るので、
ここでは「開いた瞬間に向こうから話しかける」までを担う。フロントが取得して表示する。

LM Studio が落ちていてもテンプレで一言返す。失敗してもサーバーは落とさない。
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from . import briefing, db
from .lmstudio_client import LMStudioError, chat_completion

log = logging.getLogger(__name__)

_SYSTEM = """あなたはユーザー専用アシスタント「PETIT」。相棒として横にいる人間のように話します。
ユーザーがアプリを開きました。あなたから自然に一言、話しかけてください。

ルール:
- 短く（1〜2文）。砕けた口調。一人称は「私」。
- 覚えている文脈（最近の流れ・作業中のこと）があれば軽く触れ、続きを促したり様子を聞く。
- 事務的な一覧・タスクの読み上げはしない。あくまで会話の切り出し。
- 文脈が無ければ、時間帯に合った軽い挨拶でよい。"""


def _time_of_day(now: datetime | None = None) -> str:
    h = (now or datetime.now()).hour
    if 5 <= h < 11:
        return "朝"
    if 11 <= h < 17:
        return "昼"
    if 17 <= h < 22:
        return "夜"
    return "深夜"


def _context_block() -> tuple[str, list[str]]:
    """Returns (recent episode text, work_in_progress list) from memory."""
    episodes = db.recent_episodes(limit=2)
    if episodes:
        latest = str(episodes[-1].get("summary") or "")
    else:
        summaries = db.recent_summaries(limit=2)
        latest = str(summaries[-1].get("summary") or "") if summaries else ""
    wip = [m["content"] for m in db.all_memory() if m.get("type") == "project"][-3:]
    return latest, wip


def generate_opener() -> dict[str, Any]:
    """Generate one proactive opening line. Never raises."""
    tod = _time_of_day()
    if tod == "朝":
        daily = briefing.create_daily_briefing()
        github = daily.get("github_review") or {}
        return {
            "message": daily["message"],
            "kind": "morning_briefing",
            "time_of_day": tod,
            "sources": {
                "tasks": len(daily.get("tasks", [])),
                "events": len(daily.get("events", [])),
                "notion_sync": daily.get("notion_sync"),
                "calendar": daily.get("calendar_source_status"),
                "github": {
                    "status": github.get("status"),
                    "changed_repositories": int(github.get("changed_count") or 0),
                    "cached": bool(github.get("cached")),
                },
            },
        }
    latest, wip = _context_block()

    context_lines = [f"今は{tod}。"]
    if latest:
        context_lines.append(f"最近の流れ: {latest}")
    if wip:
        context_lines.append("作業中: " + " / ".join(wip))
    context = "\n".join(context_lines)

    try:
        message = chat_completion(
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": context},
            ],
            tools=None,
            temperature=0.8,
        )
        text = (message.get("content") or "").strip()
        if text:
            return {"message": text, "kind": "llm", "time_of_day": tod}
    except LMStudioError as exc:
        log.debug("proactive opener via LLM failed: %s", exc)

    return {"message": _fallback(tod, latest, wip), "kind": "template", "time_of_day": tod}


def _fallback(tod: str, latest: str, wip: list[str]) -> str:
    greet = {"朝": "おはよう。", "昼": "やっほー。", "夜": "おつかれさま。", "深夜": "まだ起きてるんだね。"}[tod]
    if wip:
        return f"{greet}{wip[-1]}の続き、やる？"
    if latest:
        return f"{greet}さっきは「{latest[:40]}」って話してたね。続きやる？"
    return f"{greet}今日はどうする？"
