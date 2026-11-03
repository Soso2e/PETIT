"""Explicit real CLI acceptance with synthetic DB/repository only; no credentials read."""
import argparse
import json
import os
from pathlib import Path
import tempfile


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live",action="store_true")
    parser.add_argument("--output",type=Path)
    parser.add_argument("--coding",action="store_true",help="Also run a real CLI coding job on a synthetic repository")
    args=parser.parse_args()
    report={"evidence":"real_cli_synthetic_data","status":"skipped","subscription_quota_used":"unknown"}
    if args.live:
        with tempfile.TemporaryDirectory(prefix="petit-agy-acceptance-",ignore_cleanup_errors=True) as tmp:
            root=Path(tmp)
            os.environ.update(PETIT_SETTINGS_DIR=str(root/"settings"),PETIT_STORAGE_DIR=str(root),PETIT_DB_PATH=str(root/"app.db"),
                PETIT_MODEL_ROUTING_PATH=str(root/"routing.json"),PETIT_BOOTSTRAP_TOKEN="")
            import sys
            sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
            from backend import config,db,tools,setup_store as settings,conversation_store as store,conversation_api as chat
            from backend import coding_jobs as jobs,antigravity_cli as cli
            config.notion_configured=lambda:False
            config.NOTION_API_KEY="";config.NOTION_TASKS_DB_ID="";config.USE_SONA_CORE=False
            from backend import chroma_client
            chroma_client.add=lambda *a,**k:None
            chroma_client.sync_structured_data=lambda *a,**k:None
            import backend.chat
            backend.chat._artifact_executor.submit=lambda *a,**k:None
            db.init_db();store.ensure_schema();tools.register_builtin_tools();jobs.ensure_schema()
            settings.update({"brain_enabled":True,"brain_transport":"cli_only","antigravity_cli_enabled":True,
                "connected":["antigravity_cli"],"priority":["antigravity_cli","codex","antigravity","deepseek"]})
            checks=[]
            result=chat.submit("synthetic-cli","cli-hello","接続確認です。短く挨拶してください。")
            checks.append({"name":"chat","ok":result["status"]=="completed","error":result.get("error")})
            result=chat.submit("synthetic-cli","cli-read","現在時刻をget_current_timeで取得して答えてください。")
            checks.append({"name":"read_tool","ok":result["status"]=="completed" and any(x["name"]=="get_current_time" for x in result.get("used_tools",[])),"error":result.get("error")})
            result=chat.submit("synthetic-cli","cli-approval","合成検証専用の予定『CLI受入テスト』を2026-11-01T12:00:00+09:00に追加してください。add_scheduleを使ってください。")
            before=0
            with db.get_connection() as c:before=c.execute("SELECT count(*) FROM calendar_events_cache").fetchone()[0]
            waiting=result["status"]=="waiting_approval" and before==0
            checks.append({"name":"approval_before_write","ok":waiting,"error":result.get("error")})
            if waiting:
                approval=store.approvals("cli-approval")[0]["approval_id"]
                done=chat.decide(approval,True)
                replay=chat.submit("synthetic-cli","cli-approval","合成検証専用の予定『CLI受入テスト』を2026-11-01T12:00:00+09:00に追加してください。add_scheduleを使ってください。")
                with db.get_connection() as c:
                    rows=c.execute("SELECT count(*) FROM calendar_events_cache").fetchone()[0]
                    receipts=c.execute("SELECT count(*) FROM effect_receipts WHERE request_id='cli-approval'").fetchone()[0]
                checks.append({"name":"approval_resume_and_replay","ok":done["status"]=="completed" and replay["reply"]==done["reply"] and rows==receipts==1,"error":done.get("error")})
            if args.coding:
                repo=root/"fixture-repo";repo.mkdir()
                jobs.git(repo,"init","-q")
                (repo/"AGENTS.md").write_text("Edit only answer.py. Preserve all existing files.\n",encoding="utf-8")
                (repo/"answer.py").write_text("ANSWER = 1\n",encoding="utf-8")
                jobs.git(repo,"add",".");jobs.git(repo,"-c","user.name=Fixture","-c","user.email=fixture@example.invalid","commit","-qm","fixture")
                settings.update({"coding_roots":[str(repo)]})
                job=jobs.create("live-coding",str(repo),"Read AGENTS.md and answer.py, change ANSWER from 1 to 2 using write_file with the SHA-256 from read_file, run_static_checks, and summarize. Do not create additional files.","antigravity_cli",approved=True)
                jobs._stop.clear();jobs.pump();done=jobs.get(job["job_id"])
                original=(repo/"answer.py").read_text()=="ANSWER = 1\n"
                changed=bool(done["workspace"] and "ANSWER = 2" in (Path(done["workspace"])/"answer.py").read_text())
                checks.append({"name":"real_cli_coding_job","ok":done["status"]=="ready_for_review" and original and changed,
                    "status":done["status"],"original_unchanged":original,"static_checks":done["checks"],"error":done["error"]})
            with db.get_connection() as c:
                usage=[json.loads(x[0]).get("usage") for x in c.execute("SELECT payload_json FROM turn_events WHERE type='antigravity_cli_step'")]
            report.update(status="completed" if all(x["ok"] for x in checks) else "failed",checks=checks,usage=usage,
                production_db_used=False,real_service_acceptance="not_verified",codex_live_acceptance="not_verified")
    rendered=json.dumps(report,ensure_ascii=False,indent=2)+"\n"
    if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(rendered,encoding="utf-8")
    print(rendered)
    return 1 if report["status"]=="failed" else 0


if __name__=="__main__":raise SystemExit(main())
