"""Real CLI acceptance of a Develop thread: edit and commit, then continue in the same CLI session.

Uses a synthetic repository and an isolated DB under a temporary directory. The production DB,
settings and repositories are not touched. Each selected CLI runs two short jobs on the user's
own CLI login, so it consumes a little of that subscription's quota.

    python scripts/smoke_development_thread.py                       # detection only
    python scripts/smoke_development_thread.py --live --provider claude_code
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile

MODEL_KEYS = {"claude_code": "claude_opus", "codex": "codex_sol", "antigravity_cli": "gemini_flash"}


def run_provider(provider, root, jobs, threads, effort):
    repo = root / ("repo-" + provider)
    repo.mkdir()
    jobs.git(repo, "init", "-q")
    jobs.git(repo, "config", "user.name", "PETIT Smoke")
    jobs.git(repo, "config", "user.email", "smoke@example.invalid")
    (repo / "answer.py").write_text("ANSWER = 1\n", encoding="utf-8")
    jobs.git(repo, "add", ".")
    jobs.git(repo, "commit", "-qm", "fixture")
    from backend import setup_store as settings
    settings.update({"coding_roots": [*settings.load()["coding_roots"], str(repo)]})
    start = jobs.git(repo, "rev-parse", "HEAD").strip()
    thread = threads.create(str(repo), "smoke " + provider)["thread_id"]
    # The token exists only in the first request. A resumed session receives the second request
    # alone, so finding the token in the second job's output proves the CLI kept its own memory.
    token = "petit-" + secrets.token_hex(4)

    def job(name, goal):
        threads.verify(thread, str(repo))
        created = jobs.create_development(name + "-" + provider, str(repo), goal, MODEL_KEYS[provider], effort,
                                          direct=True, thread_id=thread)
        jobs.pump()
        return jobs.get(created["id"])

    first = job("first", "answer.py の ANSWER を 2 に変更し、ローカルにcommitしてください。pushはしないでください。"
                         "あとで使う合言葉は「" + token + "」です。覚えておいてください。")
    committed = jobs.git(repo, "rev-parse", "HEAD").strip() != start
    second = job("second", "最初に伝えた合言葉だけを1行で書いた notes.txt を作り、ローカルにcommitしてください。pushはしないでください。")
    kinds = [item["kind"] for item in second["events"]]
    notes = repo / "notes.txt"
    remembered = notes.is_file() and token in notes.read_text(encoding="utf-8", errors="replace")
    steps = [item["detail"] for item in first["events"] + second["events"] if item["kind"] == "cli_tool"]
    checks = {
        "first_job_ready_for_review": first["status"] == "ready_for_review",
        "first_job_edited_file": "ANSWER = 2" in (repo / "answer.py").read_text(encoding="utf-8"),
        "first_job_committed": committed,
        "second_job_ready_for_review": second["status"] == "ready_for_review",
        "workspace_continued_after_commit": "workspace_continued" in kinds,
        "cli_session_resumed": "session_resumed" in kinds and "session_restarted" not in kinds,
        "cli_remembered_first_request": remembered,
        "tool_steps_recorded": bool(steps),
    }
    return {"provider": provider, "ok": all(checks.values()), "checks": checks,
            "statuses": [first["status"], second["status"]], "errors": [first["error"], second["error"]],
            "tool_steps": len(steps)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true", help="Run the real CLIs. Without it, only detection runs.")
    parser.add_argument("--provider", action="append", choices=sorted(MODEL_KEYS),
                        help="CLI to verify (repeatable). Default: every detected and authenticated CLI.")
    parser.add_argument("--effort", default="low", choices=["low", "medium", "high"])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = {"evidence": "real_cli_synthetic_repository", "status": "skipped", "production_db_used": False}
    with tempfile.TemporaryDirectory(prefix="petit-develop-smoke-", ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        os.environ.update(PETIT_SETTINGS_DIR=str(root / "settings"), PETIT_STORAGE_DIR=str(root / "storage"),
                          PETIT_DB_PATH=str(root / "app.db"), PETIT_MODEL_ROUTING_PATH=str(root / "routing.json"),
                          PETIT_BOOTSTRAP_TOKEN="")
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from backend import brain_priority, coding_jobs as jobs, conversation_store, db, development_models
        from backend import development_threads as threads, setup_store as settings
        db.init_db()
        conversation_store.ensure_schema()
        jobs.ensure_schema()
        settings.update({"connected": sorted(MODEL_KEYS), "antigravity_cli_enabled": True, "claude_code_enabled": True,
                         "coding_roots": []})
        usage = development_models.usage()
        detected = {provider: {"installed": bool(brain_priority.target(provider)["configured"]),
                               "available": bool(usage[key]["available"])}
                    for provider, key in MODEL_KEYS.items()}
        report["detected"] = detected
        if args.live:
            jobs._stop.clear()
            selected = args.provider or [name for name, state in detected.items() if state["available"]]
            results = []
            for provider in selected:
                if not detected[provider]["available"]:
                    results.append({"provider": provider, "ok": False, "skipped": "not_installed_or_not_authenticated"})
                    continue
                try:
                    results.append(run_provider(provider, root, jobs, threads, args.effort))
                except Exception as exc:  # noqa: BLE001 - report the failure instead of losing the other CLIs
                    results.append({"provider": provider, "ok": False, "error": type(exc).__name__ + ": " + str(exc)[:300]})
            report.update(results=results,
                          status="completed" if results and all(item["ok"] for item in results) else "failed")
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
