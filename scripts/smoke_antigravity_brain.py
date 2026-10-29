"""Real SDK + LM Studio against a disposable PETIT DB. No real account writes."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:1234/v1")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must be a new file")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    with tempfile.TemporaryDirectory(prefix="petit-sdk-smoke-") as temp:
        os.environ.update(PETIT_STORAGE_DIR=temp, PETIT_DB_PATH=str(Path(temp) / "app.db"),
                          PETIT_MODEL_ROUTING_PATH=str(Path(temp) / "routing.json"),
                          PETIT_CHAT_PROFILE="antigravity_sdk", PETIT_ANTIGRAVITY_AUTH="local",
                          PETIT_ANTIGRAVITY_BASE_URL=args.base_url, PETIT_ANTIGRAVITY_MODEL=args.model,
                          PETIT_AUTO_SUMMARY_ENABLED="0", PETIT_DAILY_INDEX_ENABLED="0")
        from backend import chat, config, conversation_api as api, conversation_store as store, db, tools
        config.notion_configured = lambda: False
        config.USE_SONA_CORE = False
        chat._artifact_executor.submit = lambda *unused: None
        db.init_db(); store.ensure_schema(); tools.register_builtin_tools()
        marker = "sdk-fixture-" + uuid.uuid4().hex[:8]
        tools.dispatch("create_task", {"title": marker})
        prompts = ["Reply with exactly: CORE_SDK_OK",
                   "petit_read_toolでget_tasksを呼び、取得したタスク名を一つだけそのまま答えて。引数JSONは{}。",
                   "前のターンで取得したタスク名を再度答えて。今回はToolを使わないで。"]
        turns = []
        for index, prompt in enumerate(prompts):
            if index == 2:
                store.recover()  # Read the next turn from persisted Core history.
            started = time.monotonic()
            result = api.submit("synthetic-sdk", str(index), prompt)
            turns.append({k: result.get(k) for k in ("status", "reply", "used_tools", "model_route", "error")})
            turns[-1]["wall_seconds"] = round(time.monotonic() - started, 3)
        replay = api.submit("synthetic-sdk", "1", prompts[1])
        os.environ["PETIT_ANTIGRAVITY_TIMEOUT_SECONDS"] = "0.05"
        timeout_started = time.monotonic()
        timed_out = api.submit("synthetic-sdk", "timeout", "Reply with exactly: MUST_TIMEOUT")
        timeout_case = {"status": timed_out["status"], "error": timed_out.get("error"),
                        "wall_seconds": round(time.monotonic() - timeout_started, 3),
                        "model_route": timed_out.get("model_route")}
        os.environ["PETIT_ANTIGRAVITY_TIMEOUT_SECONDS"] = "90"
        with ThreadPoolExecutor(max_workers=1) as executor:
            cancel_started = time.monotonic()
            pending = executor.submit(api.submit, "synthetic-sdk", "cancel", "List the integers 1 to 3000, one per line. Do not summarize or use tools.")
            time.sleep(4)
            cancellation_exercised = not pending.done()
            api.cancel_turn("cancel")
            cancelled = pending.result(timeout=20)
        cancel_case = {"status": cancelled["status"], "cancellation_exercised": cancellation_exercised,
                       "wall_seconds": round(time.monotonic() - cancel_started, 3),
                       "effects": cancelled.get("effects"), "model_route": cancelled.get("model_route")}
        passed = (all(t["status"] == "completed" and t["model_route"]["provider"] == "antigravity_sdk" for t in turns)
                  and turns[0]["reply"].strip() == "CORE_SDK_OK"
                  and marker in turns[1]["reply"] and marker in turns[2]["reply"]
                  and any(t["name"] == "get_tasks" for t in turns[1]["used_tools"] or [])
                  and replay["reply"] == turns[1]["reply"]
                  and timed_out["status"] == "failed" and "タイムアウト" in timed_out.get("error", "")
                  and cancellation_exercised and cancelled["status"] == "cancelled")
        report = {"status": "passed" if passed else "failed", "synthetic_data_only": True,
                  "sdk_runtime": "real", "inference": "real_lm_studio", "fixture_marker": marker,
                  "core_recovery_invoked": True, "same_request_replay_matches": replay["reply"] == turns[1]["reply"],
                  "turns": turns, "timeout": timeout_case, "cancel": cancel_case,
                  "packaged_desktop_verified": False}
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": report["status"], "turns": len(turns), "report": str(args.output)}, ensure_ascii=False))
        return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
