"""Real HTTP/Web fixture with synthetic coding agent and disposable repository."""
import json

from . import setup_ui_server as base
from backend import brain, coding_jobs as jobs, coding_agents, development_models, setup_store as settings

repo=base._root/"fixture-repository";repo.mkdir(exist_ok=True)
if not (repo/".git").exists():
    jobs.git(repo,"init","-q")
    (repo/"AGENTS.md").write_text("Preserve existing files.\n",encoding="utf-8")
    (repo/"answer.py").write_text("ANSWER = 1\n",encoding="utf-8")
    jobs.git(repo,"add",".");jobs.git(repo,"-c","user.name=Fixture","-c","user.email=fixture@example.invalid","commit","-qm","fixture")
settings.update({"coding_roots":[str(repo)],"connected":["codex"]})
development_models.usage = lambda: {
    key: {"label": spec[2], "provider": spec[0], "available": key == "codex_sol", "five_hour": 83, "weekly": 45}
    for key, spec in development_models.MODELS.items()
}


def synthetic(provider,target,goal,invoke,check,progress,**kwargs):
    invoke("read_file",{"path":"AGENTS.md"})
    old=invoke("read_file",{"path":"answer.py"})
    result=invoke("write_file",{"path":"answer.py","content":"ANSWER = 2\n","expected_sha256":old["sha256"]})
    if not result.get("saved"):raise ValueError("synthetic_write_failed")
    return "合成CLIでanswer.pyを変更しました。実テストは未実施です。"
coding_agents.run=synthetic


def synthetic_chat(messages, **kwargs):
    if messages[-1]["content"] == "fixture-chat-dev":
        return {"role": "assistant", "content": "", "tool_calls": [{"id": "fixture", "type": "function", "function": {
            "name": "propose_development_job",
            "arguments": json.dumps({"repository": str(repo), "goal": "Chat の合成開発", "model_key": "codex_sol"}),
        }}]}
    return {"role": "assistant", "content": "開始を確認してください。"}


brain.lmstudio_client.chat_completion = synthetic_chat
brain.check_provider = lambda thread: {"provider": "lm_studio", "profile": "local", "model": "synthetic",
                                      "base_url": "http://localhost", "configured": True}
app=base.app
app.router.add_event_handler("startup",jobs.start)
app.router.add_event_handler("shutdown",jobs.stop)
