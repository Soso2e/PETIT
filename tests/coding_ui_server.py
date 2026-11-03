"""Real HTTP/Web fixture with synthetic coding agent and disposable repository."""
from . import setup_ui_server as base
from backend import coding_jobs as jobs, coding_agents, setup_store as settings
from pathlib import Path

repo=base._root/"fixture-repository";repo.mkdir(exist_ok=True)
if not (repo/".git").exists():
    jobs.git(repo,"init","-q")
    (repo/"AGENTS.md").write_text("Preserve existing files.\n",encoding="utf-8")
    (repo/"answer.py").write_text("ANSWER = 1\n",encoding="utf-8")
    jobs.git(repo,"add",".");jobs.git(repo,"-c","user.name=Fixture","-c","user.email=fixture@example.invalid","commit","-qm","fixture")
settings.update({"coding_roots":[str(repo)],"connected":["codex"]})
def synthetic(provider,target,goal,invoke,check,progress):
    invoke("read_file",{"path":"AGENTS.md"})
    old=invoke("read_file",{"path":"answer.py"})
    result=invoke("write_file",{"path":"answer.py","content":"ANSWER = 2\n","expected_sha256":old["sha256"]})
    if not result.get("saved"):raise ValueError("synthetic_write_failed")
    return "合成CLIでanswer.pyを変更しました。実テストは未実施です。"
coding_agents.run=synthetic
app=base.app
app.router.add_event_handler("startup",jobs.start)
app.router.add_event_handler("shutdown",jobs.stop)
