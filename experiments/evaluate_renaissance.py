"""Real configured Brain / synthetic local data. Never opens the user's DB.

Run after Core + Memory + Project-folder changes are combined. The optional
key file supplies only PETIT_DEEPSEEK_API_KEY; no file text enters model context.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from unittest.mock import patch


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.key_file:
        for line in args.key_file.read_text(encoding="utf-8-sig").splitlines():
            if line.startswith("PETIT_DEEPSEEK_API_KEY="):
                os.environ["PETIT_DEEPSEEK_API_KEY"] = line.split("=", 1)[1].strip().strip("\"'")
    if not os.getenv("PETIT_DEEPSEEK_API_KEY"):
        print("SKIP: configured DeepSeek credential unavailable")
        return 77
    with tempfile.TemporaryDirectory(prefix="petit-renaissance-eval-") as directory:
        os.environ["PETIT_STORAGE_DIR"] = directory
        os.environ["PETIT_DB_PATH"] = str(Path(directory) / "app.db")
        os.environ["PETIT_MODEL_ROUTING_PATH"] = str(Path(directory) / "routing.json")
        os.environ["PETIT_CHAT_PROFILE"] = "deepseek_flash"
        from backend import brain, calendar_sync, chat, chroma_client, config, conversation_api as api
        from backend import conversation_store as store, db, project_continuity, project_workspaces, tools, workspace_context
        config.notion_configured = lambda: False
        config.USE_SONA_CORE = False
        config.WORKSPACE_CONTEXT_ENABLED = config.WORKSPACE_LOCAL_DEVELOPMENT_ENABLED = True
        config.WORKSPACE_CONTEXT_FOREGROUND_ENABLED = False
        root = Path(directory) / "Python_Tools"
        root.mkdir()
        (root / "PROGRESS.md").write_text(
            "# 卒研fixture\n骨格の実装まで。自動テスト・実機検証は未実施。次は比較実験。", encoding="utf-8")
        def git(*arguments):
            subprocess.run(["git", "-C", str(root), *arguments], check=True, capture_output=True)
        git("init", "-b", "main")
        git("add", "PROGRESS.md")
        git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "fixture")
        config.WORKSPACE_CONTEXT_DIRS = [root]
        db.init_db()
        store.ensure_schema()
        project = project_continuity.create_project("卒研")
        project_workspaces.link(project["id"], str(root))
        workspace_context._observer.refresh()
        task = json.loads(tools.dispatch("create_task", {"title": "卒研の発表準備", "project_id": project["id"]}))["task"]
        with db.get_connection() as connection:
            connection.execute(
                "INSERT INTO calendar_events_cache(source,title,start_time,updated_at) VALUES('local',?,?,?)",
                ("卒研発表", "2026-11-10T10:00:00+09:00", db.now_iso()))
        store.create_thread("fixture-discord", source="discord")
        db.save_conversation("卒研の実験条件は解像度512、比較対象は3方式。",
                             "解像度512・3方式で比較する決定を確認した。", session_id="fixture-discord")
        cases = [
            ("progress", "fixture-main", "このところ卒研のコード側はどこまで進んでる？"),
            ("remember", "fixture-main", "発表日は2026年11月10日の10時だったね。覚えておいてほしい。"),
            ("avoid_duplicate", "fixture-main", "記録にある発表日はもう重複して保存しなくていい。今なにから手を付けようか。"),
            ("start", "fixture-main", "じゃ、さっきの卒研の発表準備を始めよう。"),
            ("original_quote", "fixture-search", "Discordで話した卒研の実験条件を、元の発言に戻って確認したい。"),
            ("quoted_command", "fixture-translation", "『卒研の作業を開始して』を英語に訳して。これは操作の依頼ではない。"),
            ("correction", "fixture-main", "発表日が2026年11月12日の10時に延期されたので、前の記憶を訂正して。"),
        ]
        rows = []
        # Only model calls are real. Index/export/external synchronization are
        # disabled so synthetic acceptance cannot touch the user's services.
        with patch.object(chat._artifact_executor, "submit"), patch.object(chroma_client, "query", return_value=None), \
             patch.object(chroma_client, "add", return_value=False), patch.object(chroma_client, "delete_ids"), \
             patch.object(calendar_sync, "sync_if_configured", return_value={"status": "fixture_local_only"}):
            for label, thread, text in cases:
                started = time.monotonic()
                result = api.submit(thread, "eval-" + label, text)
                with db.get_connection() as connection:
                    memory_count = connection.execute("SELECT COUNT(*) FROM memory").fetchone()[0]
                    work_count = connection.execute("SELECT COUNT(*) FROM work_sessions").fetchone()[0] if connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE name='work_sessions'").fetchone() else 0
                    calendar_count = connection.execute("SELECT COUNT(*) FROM calendar_events_cache").fetchone()[0]
                    replaced = connection.execute("SELECT COUNT(*) FROM memory WHERE superseded_by IS NOT NULL").fetchone()[0]
                names = [t["name"] for t in result.get("used_tools", [])]
                passed = result["status"] == "completed"
                if label == "progress": passed &= "get_local_development_status" in names
                if label == "remember": passed &= memory_count == 1 and calendar_count == 1
                if label == "avoid_duplicate": passed &= memory_count == 1 and calendar_count == 1
                if label == "start": passed &= "start_work_session" in names and work_count == 1
                if label == "original_quote": passed &= "search_conversations" in names
                if label == "quoted_command": passed &= not result.get("effects")
                if label == "correction": passed &= replaced >= 1
                row = {"case": label, "passed": bool(passed), "status": result["status"],
                       "tools": names, "memory_rows": memory_count, "work_rows": work_count,
                       "calendar_rows": calendar_count, "replaced_memory_rows": replaced,
                       "elapsed_ms": round((time.monotonic() - started) * 1000),
                       "error": result.get("error"), "reply": result.get("reply", "")}
                row["tool_calls"] = result.get("used_tools", [])
                rows.append(row)
                print(json.dumps({k: v for k, v in row.items() if k not in {"reply", "tool_calls"}}, ensure_ascii=False), flush=True)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"provider": "configured_deepseek_flash", "data": "synthetic",
            "external_sync_and_embedding": "disabled", "real_discord_and_devices": "not_tested",
            "passed": sum(r["passed"] for r in rows), "cases": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if all(r["passed"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
