"""#368 synthetic-context sizing and unauthenticated official protocol probe.

Never borrows credentials or sends a model prompt. Outputs only counts, timings,
protocol support and an unknown marker for real inference/usage.
"""
from __future__ import annotations
import ast
import json
import os
from pathlib import Path
import statistics
import subprocess
import tempfile
import time
from unittest.mock import patch


def main():
    with tempfile.TemporaryDirectory(prefix="petit-368-probe-") as tmp:
        root = Path(tmp)
        os.environ.update(PETIT_STORAGE_DIR=tmp, PETIT_SETTINGS_DIR=str(root / "settings"),
                          PETIT_DB_PATH=str(root / "app.db"), PETIT_AUTO_SUMMARY_ENABLED="0", PETIT_DAILY_INDEX_ENABLED="0")
        (root / "AGENTS.md").write_text("Parent repository instructions must not be loaded.", encoding="utf-8")
        from backend import (agent_workspace, brain, brain_catalog, codex_brain, config, conversation_store as store,
                             db, external_brain, request_context, tools)
        db.init_db(); store.ensure_schema(); tools.register_builtin_tools()
        store.create_thread("synthetic");store.accept("synthetic", "synthetic-1", {"message":"こんにちは"});store.claim("synthetic-1")
        old = subprocess.check_output(["git", "show", "3620ea1:backend/brain.py"], text=True, encoding="utf-8")
        names = next(ast.literal_eval(node.value) for node in ast.parse(old).body if isinstance(node, ast.Assign)
                     and any(isinstance(x, ast.Name) and x.id == "PUBLIC_TOOLS" for x in node.targets))
        baseline = [x for x in tools.openai_tools_schema() if x["function"]["name"] in names]
        with request_context.bind(request_id="synthetic-1",session_id="synthetic",is_admin=True):
            catalog = brain_catalog.Catalog()
            instructions,prompt = external_brain.context("synthetic-1")
            report = {"baseline_main":"3620ea1", "synthetic_data_only":True,
                "old_schema_count":len(baseline), "old_schema_chars":len(store.encode(baseline)),
                "initial_schema_count":len(catalog.schemas()), "initial_schema_chars":len(store.encode(catalog.schemas())),
                "capability_index_chars":len(catalog.index()), "cli_instructions_chars":len(instructions),
                "cli_prompt_chars":len(prompt), "tokens":None, "real_inference":None,
                "conversation_p50_seconds":None,"conversation_p95_seconds":None,"tool_success_rate":None}
        binary = codex_brain.executable()
        if binary:
            report["cli_version"] = subprocess.check_output([binary,"--version"], text=True).strip()
            times = []
            modes = {}
            for mode in ("disabled", "cached", "live"):
                started = time.monotonic()
                client = codex_brain.RPC(web_search=mode)
                try:
                    account = client.request("account/read", {"refreshToken":False})
                    result = client.request("thread/start", {"cwd":str(client.workspace),"approvalPolicy":"never",
                        "sandbox":"read-only","ephemeral":False,"dynamicTools":[]})
                    sources = result.get("instructionSources") or []
                    modes[mode] = {"configured_without_query":True,
                        "agents_md_loaded":sources == [str(client.workspace / "AGENTS.md")],
                        "authenticated":bool(account.get("account")),"inference":None}
                    times.append(round(time.monotonic()-started,4))
                finally:client.close()
            report.update(protocol_modes=modes, startup_to_thread_seconds=times,
                          startup_to_thread_median_seconds=round(statistics.median(times),4),
                          empty_thread_resume="No model turn was sent; persistence of a completed conversation is unverified")
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":main()
