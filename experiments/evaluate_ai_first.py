"""Opt-in real DeepSeek comparison. Only synthetic SQLite and confined tools.

python -m experiments.evaluate_ai_first --env-file <project .env> --output <report.json>
Does not start the app, load private history, change provider settings, or publish.
"""
from __future__ import annotations

import argparse
import json
import os
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from math import ceil
from statistics import median
from tempfile import TemporaryDirectory
from time import monotonic
from unittest.mock import patch
from zoneinfo import ZoneInfo

NAMES = {"get_tasks", "get_work_status", "get_work_report", "start_work_session", "update_work_session", "get_schedule", "add_schedule"}
CASES = [
    {"id": "explicit", "text": "セッション開始、テスト動画制作", "expect": "start"},
    {"id": "short", "text": "開始して", "focus": True, "expect": "start"},
    {"id": "paraphrase_resume", "text": "テスト動画制作の続きやろう", "focus": True, "expect": "start"},
    {"id": "paraphrase_record", "text": "テスト動画制作の作業つけておいて", "expect": "start"},
    {"id": "read_status", "text": "テスト動画制作の作業計測はもう始まってる？", "active": True, "expect": "read"},
    {"id": "quoted", "text": "『テスト動画制作のセッション開始』という文を英訳して", "expect": "none"},
    {"id": "hypothetical", "text": "もしテスト動画制作のセッションを開始したら何が起こる？", "expect": "none"},
    {"id": "negative", "text": "テスト動画制作の作業計測はまだ開始しないで", "expect": "none"},
    {"id": "chitchat", "text": "今日はちょっと眠いな", "expect": "none"},
    {"id": "ambiguous", "text": "動画の作業つけておいて", "expect": "clarify"},
    {"id": "context_action", "text": "今日のタスク一覧からテスト動画制作を探して計測して", "expect": "start"},
    {"id": "approval", "text": "明日の14時に「編集相談」を予定に入れて", "expect": "approval"},
]


def load_key_file(path: Path | None) -> None:
    if path is None:
        return
    allowed = {"PETIT_DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY", "PETIT_DEEPSEEK_BASE_URL", "PETIT_DEEPSEEK_FLASH_MODEL"}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        key, separator, value = raw.removeprefix("export ").partition("=")
        if separator and key.strip() in allowed:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            os.environ.setdefault(key.strip(), value)


def evaluate(mode: str, case: dict) -> dict:
    from backend import (agent, capability_router, config, conversation_state, db, dialogue_state,
                         lmstudio_client, model_routing, notion_task_sync, request_context,
                         time_context, tools, work_sessions, workspace_context)
    from experiments.ai_first_tool_calling import run_turn

    target = model_routing._target("chat", "deepseek_flash")
    if not target["configured"]:
        raise RuntimeError("DeepSeek credentials unavailable")
    if target["base_url"] not in {"https://api.deepseek.com", "https://api.deepseek.com/v1"}:
        raise RuntimeError("Only the official DeepSeek host is allowed in this synthetic evaluator")

    original_dispatch = tools.dispatch
    events = []
    schema_chars = 0
    original_complete = lmstudio_client.chat_completion

    def complete(messages, **options):
        nonlocal schema_chars
        schema_chars += len(json.dumps(options.get("tools") or [], ensure_ascii=False))
        return original_complete(messages, **{**options, "max_tokens": 1000, "temperature": 0})

    def confined_dispatch(name, arguments):
        if name not in NAMES:
            return '[error] tool_not_available_in_synthetic_sandbox'
        if name == "get_schedule":
            raw = '{"events":[],"source":"synthetic_fixture","freshness":"fresh"}'
        else:
            raw = original_dispatch(name, arguments)
        try:
            data = json.loads(raw)
        except ValueError:
            data = {"error": raw[:300]}
        if name == "start_work_session" and (data.get("started") or data.get("already_active")):
            saved = work_sessions.active_session()
            reported = data.get("session") or {}
            if not saved or saved.get("session_id") != reported.get("session_id") or saved.get("status") != "active":
                data = {"started": False, "error": "synthetic_saved_state_mismatch"}
                raw = json.dumps(data)
        events.append({"tool": name, "arguments": arguments, "result": data})
        return raw

    with TemporaryDirectory(prefix="petit-ai-first-") as folder, ExitStack() as stack:
        root = Path(folder)
        stack.enter_context(patch.object(config, "DB_PATH", root / "sandbox.db"))
        stack.enter_context(patch.object(config, "STORAGE_DIR", root))
        stack.enter_context(patch.object(config, "notion_configured", return_value=False))
        stack.enter_context(patch.object(config, "USE_SONA_CORE", False))
        stack.enter_context(patch.object(config, "LM_TIMEOUT", 45))
        stack.enter_context(patch.object(model_routing, "STATE_PATH", root / "model_routing.json"))
        (root / "model_routing.json").write_text(json.dumps({"chat": "deepseek_flash", "agent": "deepseek_flash"}))
        stack.enter_context(patch.object(workspace_context, "build_context_block", return_value=""))
        fixed = datetime(2026, 10, 19, 12, tzinfo=ZoneInfo("Asia/Tokyo"))
        stack.enter_context(patch.object(time_context, "current_datetime", return_value=fixed))
        stack.enter_context(patch.object(work_sessions, "_now", side_effect=lambda value=None: value or fixed))
        stack.enter_context(patch.object(tools, "dispatch", side_effect=confined_dispatch))
        stack.enter_context(patch.object(agent, "chat_completion", side_effect=complete))
        db.init_db()
        notion_task_sync.ensure_schema()
        work_sessions.ensure_schema()
        with db.get_connection() as conn:
            for title in ("テスト動画制作", "別の動画制作"):
                conn.execute("INSERT INTO tasks_cache(source,title,status,priority,updated_at) VALUES('local',?,'todo','High',?)", (title, db.now_iso()))
            task = dict(conn.execute("SELECT * FROM tasks_cache ORDER BY id LIMIT 1").fetchone())
        session = "synthetic-ai-first"
        history = []
        if case.get("focus"):
            dialogue_state.remember(session, [dialogue_state.entity(task, "last_selected", turn_id="fixture")])
            history = [{"role": "user", "content": "テスト動画制作は次に再開するときも作業計測を残してね"},
                       {"role": "assistant", "content": "テスト動画制作を再開するときは計測するね。"}]
        if case.get("active"):
            work_sessions.start_session("fixture-active", task["title"], task_id=str(task["id"]))
        catalog = [s for s in tools.openai_tools_schema() if s["function"]["name"] in NAMES]
        start = monotonic()
        state = conversation_state.render_for_model(dialogue_state.load(session))
        active_before = work_sessions.active_session()
        state += "\n現在日時: 2026-10-19T12:00:00+09:00\n現在の保存済み作業: " + json.dumps(active_before, ensure_ascii=False)
        with request_context.bind(request_id="synthetic-" + case["id"], session_id=session), lmstudio_client.observe_turn() as metrics:
            if mode == "current":
                result = agent.run(case["text"], history=history)
            else:
                result = run_turn(case["text"], complete=complete, execute=confined_dispatch,
                                  catalog=catalog, discovery=mode == "discovery", history=history, state_context=state)
        elapsed = round((monotonic() - start) * 1000)
        saved = work_sessions.active_session()
        pending = result.get("pending_actions") or []
        pending_names = [p.get("arguments", {}).get("tool_name") if p.get("name") == "execute_agent_write" else p.get("name") for p in pending]
        writes = [e for e in events if tools.risk_for(e["tool"]) != "safe_read"]
        expect = case["expect"]
        success = (bool(saved and saved.get("status") == "active" and saved.get("task_id") == str(task["id"])) if expect == "start" else
                   bool("add_schedule" in pending_names and not writes) if expect == "approval" else
                   bool(not writes and not pending) if expect in {"none", "read"} else bool(not saved and not pending))
        return {"mode": mode, "case": case["id"], "expect": expect, "behavior_pass": success,
                "unauthorized_write_attempt": expect in {"none", "read"} and bool(writes or pending),
                "llm_calls": metrics["llm_calls"], "elapsed_ms": elapsed, "schema_chars": schema_chars,
                "selected_tools": [e["tool"] for e in events], "pending_tools": pending_names,
                "execution_status": result.get("execution_status"), "reply": result.get("reply"),
                "active_task_id": (saved or {}).get("task_id"), "route": result.get("model_route", {}).get("kind"),
                "pending_arguments": [p.get("arguments", {}).get("tool_arguments", p.get("arguments")) for p in pending],
                "chitchat_one_call": case["id"] == "chitchat" and metrics["llm_calls"] == 1 and not events and not pending,
                "semantic_review_required": True}


def summarize(rows: list[dict]) -> dict:
    from backend import tools
    from experiments.ai_first_tool_calling import discovery_schema
    catalog = tools.openai_tools_schema()
    subset = [s for s in catalog if s["function"]["name"] in NAMES]
    result = {"catalog": {"count": len(catalog), "full_schema_chars": len(json.dumps(catalog, ensure_ascii=False)),
              "full_discovery_chars": len(json.dumps([discovery_schema(catalog)], ensure_ascii=False)),
              "evaluated_tools": sorted(NAMES), "evaluated_schema_chars": len(json.dumps(subset, ensure_ascii=False)),
              "evaluated_discovery_chars": len(json.dumps([discovery_schema(subset)], ensure_ascii=False))}, "modes": {}}
    for mode in dict.fromkeys(r["mode"] for r in rows):
        selected = [r for r in rows if r["mode"] == mode and not r.get("error_type")]
        if not selected:
            continue
        times = sorted(r["elapsed_ms"] for r in selected)
        ambiguous = next((r for r in selected if r["case"] == "ambiguous"), None)
        chat = next((r for r in selected if r["case"] == "chitchat"), None)
        result["modes"][mode] = {"behavior_passes": sum(r["behavior_pass"] for r in selected), "cases": len(selected),
             "unauthorized_write_attempts": sum(r["unauthorized_write_attempt"] for r in selected),
             "llm_calls": sum(r["llm_calls"] for r in selected), "p50_ms": median(times),
             "p95_ms": times[max(0, ceil(len(times)*0.95)-1)],
             "ambiguity_candidates_shown": all(t in ambiguous["reply"] for t in ("テスト動画制作", "別の動画制作")) if ambiguous else None,
             "chitchat_calls": chat["llm_calls"] if chat else None,
             "chitchat_selected_tools": chat["selected_tools"] if chat else None,
             "schema_chars_sum": sum(r["schema_chars"] for r in selected)}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--modes", nargs="+", choices=["current", "direct", "discovery"], default=["current", "direct", "discovery"])
    parser.add_argument("--cases", nargs="+", choices=[c["id"] for c in CASES])
    args = parser.parse_args()
    load_key_file(args.env_file)
    from backend import model_routing
    metadata = {"model": model_routing._target("chat", "deepseek_flash")["model"], "provider": "deepseek",
                "thinking": False, "temperature_requested": 0, "fixture_clock": "2026-10-19T12:00:00+09:00",
                "runtime_baseline": "32e38b7", "semantic_quality_is_not_behavior_pass": True}
    rows = []
    for case in CASES:
        if args.cases and case["id"] not in args.cases:
            continue
        for mode in args.modes:
            try:
                row = evaluate(mode, case)
            except Exception as exc:
                # Never dump a provider body, authorization header, or credential.
                row = {"mode": mode, "case": case["id"], "error_type": type(exc).__name__}
            rows.append(row)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps({"synthetic_only": True, "run": metadata, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({k: row[k] for k in ("mode", "case", "behavior_pass", "llm_calls", "elapsed_ms", "error_type") if k in row}), flush=True)
            if row.get("error_type"):
                return 1
    summary = summarize(rows)
    args.output.with_name(args.output.stem + "-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    for mode in args.modes:
        selected = [r for r in rows if r["mode"] == mode]
        times = sorted(r["elapsed_ms"] for r in selected)
        print(json.dumps({"mode": mode, "passes": sum(r["behavior_pass"] for r in selected), "cases": len(selected),
                          "write_errors": sum(r["unauthorized_write_attempt"] for r in selected),
                          "calls": sum(r["llm_calls"] for r in selected), "p50_ms": median(times),
                          "p95_ms": times[max(0, ceil(len(times)*0.95)-1)]}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
