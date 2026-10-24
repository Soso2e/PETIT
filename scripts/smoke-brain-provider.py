"""Opt-in real Provider smoke with synthetic data and a temporary DB/workspace.

Run from the repository root. No production DB, Notion, embeddings or artifacts.
Only explicitly named provider credentials are read from --env-file; never printed.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=["gemini", "deepseek_flash"], default="gemini")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fallback-probe", action="store_true", help="Inject a Gemini 429, then call real DeepSeek")
    args = parser.parse_args()
    keys = {"GEMINI_API_KEY", "PETIT_GEMINI_API_KEY", "PETIT_GEMINI_MODEL", "PETIT_DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY"}
    if args.env_file:
        for line in args.env_file.read_text(encoding="utf-8-sig").splitlines():
            key, sep, value = line.strip().removeprefix("export ").partition("=")
            if sep and key.strip() in keys:
                os.environ.setdefault(key.strip(), value.strip().strip('"\''))
    credential_names = (["PETIT_DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY"] if args.fallback_probe or args.profile == "deepseek_flash"
                        else ["PETIT_GEMINI_API_KEY", "GEMINI_API_KEY"])
    if not any(os.getenv(k) for k in credential_names):
        report = {"status": "skipped", "profile": args.profile, "reason": "credential_not_configured", "real_provider_verified": False,
                  "verified_providers": [], "checked_at_utc": datetime.now(timezone.utc).isoformat()}
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report))
        return 0

    with tempfile.TemporaryDirectory(prefix="petit-provider-smoke-") as directory, ExitStack() as stack:
        root = Path(directory)
        os.environ.update(PETIT_STORAGE_DIR=str(root), PETIT_DB_PATH=str(root / "app.db"),
                          PETIT_MODEL_ROUTING_PATH=str(root / "routing.json"), PETIT_CHAT_PROFILE=args.profile,
                          PETIT_DEEPSEEK_FALLBACK_THREADS="provider-smoke", PETIT_AUTO_SUMMARY_ENABLED="0",
                          PETIT_DAILY_INDEX_ENABLED="0")
        from backend import (brain, config, conversation_api as api, conversation_store as store, db,
                             lmstudio_client, model_routing, project_continuity, project_workspaces, tools, workspace_context)
        workspace = root / "graduation"
        workspace.mkdir()
        (workspace / "PROGRESS.md").write_text("# 合成卒研\n実装済み。実機での受入は未確認。次は実機検証。", encoding="utf-8")
        subprocess.run(["git", "init", "-q", "-b", "main", str(workspace)], check=True, capture_output=True)
        for key, value in {"USE_SONA_CORE": False, "notion_configured": lambda: False,
                           "WORKSPACE_CONTEXT_ENABLED": True, "WORKSPACE_LOCAL_DEVELOPMENT_ENABLED": True,
                           "WORKSPACE_CONTEXT_FOREGROUND_ENABLED": False, "WORKSPACE_CONTEXT_DIRS": [workspace]}.items():
            stack.enter_context(patch.object(config, key, value))
        for target in ("backend.chroma_client.sync_structured_data", "backend.chroma_client.add",
                       "backend.chroma_client.delete_ids", "backend.chat._artifact_executor.submit"):
            stack.enter_context(patch(target))
        db.init_db()
        store.ensure_schema()
        tools.register_builtin_tools()
        project = project_continuity.create_project("合成卒研")
        project_workspaces.link(project["id"], str(workspace))
        observer = workspace_context.WorkspaceObserver()
        stack.enter_context(patch.object(workspace_context, "_observer", observer))
        observer.refresh()
        if args.fallback_probe:
            os.environ["PETIT_CHAT_PROFILE"] = "gemini"
            os.environ.setdefault("PETIT_GEMINI_API_KEY", "synthetic-not-sent")
            real_post = lmstudio_client.httpx.post
            def fault(url, **kwargs):
                if url.startswith("https://generativelanguage.googleapis.com/"):
                    return lmstudio_client.httpx.Response(429, json={}, request=lmstudio_client.httpx.Request("POST", url))
                return real_post(url, **kwargs)
            stack.enter_context(patch.object(lmstudio_client.httpx, "post", side_effect=fault))
        cases = [("chat", "こんにちは。短く挨拶して。", set()),
                 ("workspace", f"合成卒研（project_id={project['id']}）の進捗どう？紐づくフォルダのPROGRESS.mdを確認して、実装済みと実機未確認を区別して教えて。",
                  {"get_local_development_status"}),
                 ("continuation", "今話した卒研について、実機検証は済んでいた？直前の文脈だけで答えて。", set())]
        records = []
        for index, (name, prompt, required) in enumerate(cases):
            result = api.submit("provider-smoke", f"smoke-{index}", prompt)
            names = {t["name"] for t in result.get("used_tools", [])}
            success = result["status"] == "completed" and bool(result["reply"]) and required <= names
            if name == "chat":
                success = success and not names
            if name == "workspace":
                success = success and "未確認" in result["reply"]
            if name == "continuation":
                success = success and any(s in result["reply"] for s in ("未確認", "まだ", "済んでい", "未実施"))
            records.append({"name": name, "passed": success, "status": result["status"],
                            "reply": result["reply"].replace(str(root), "<synthetic-workspace>"),
                            "tools": sorted(names), "error": result.get("error"), "model_route": result.get("model_route")})
        report = {"status": "passed" if all(r["passed"] for r in records) else "failed",
                  "profile": args.profile, "fault_injected_primary": args.fallback_probe,
                  "real_provider_verified": any(r["status"] == "completed" for r in records),
                  "verified_providers": sorted({r["model_route"]["provider"] for r in records if r["status"] == "completed"}),
                  "checked_at_utc": datetime.now(timezone.utc).isoformat(), "cases": records}
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": report["status"], "cases": [{"name": r["name"], "passed": r["passed"]} for r in records]}))
        return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
