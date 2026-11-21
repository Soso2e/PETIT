import json
from unittest.mock import patch

from tests.test_setup_integrations import isolated  # noqa: F401 - autouse isolation
from backend import brain, coding_jobs, conversation_api, development_models, lmstudio_client


def _stub_front_brain(monkeypatch, calls_log):
    monkeypatch.setattr(brain, "check_provider", lambda thread: {"provider": "deepseek", "model": "deepseek-chat"})
    monkeypatch.setattr(
        development_models,
        "select",
        lambda key, effort, lightweight=False: (
            "claude_code",
            "sonnet",
            {"model_key": "claude_sonnet", "label": "Claude Sonnet 5.5", "effort": effort, "quota": {}},
        ),
    )

    def fake_chat(messages, tools=None, route="chat", max_tokens=1600, target_override=None, **kwargs):
        calls_log.append(messages)
        if len(calls_log) == 1:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "propose_development_job",
                            "arguments": json.dumps({"repository": "", "goal": "feat_nico を含む mp3 を探して"}),
                        },
                    }
                ],
            }
        return {"role": "assistant", "content": "提案として置けました。"}

    monkeypatch.setattr(lmstudio_client, "chat_completion", fake_chat)


def test_discord_propose_development_job_runs_directly_and_returns_cli_summary(monkeypatch):
    coding_jobs.ensure_schema()
    calls_log = []
    _stub_front_brain(monkeypatch, calls_log)

    def fake_wait(job_id, *, timeout=540.0, poll_interval=0.5, should_cancel=None):
        job = coding_jobs.get(job_id)
        assert job["status"] == "queued"
        assert job["model"] == "sonnet"
        coding_jobs.finish(job_id, "ready_for_review", summary="C:\\Music\\track_feat_nico.mp3")
        return coding_jobs.get(job_id)

    monkeypatch.setattr(coding_jobs, "wait_for_job", fake_wait)

    result = conversation_api.submit(
        "discord:12345",
        "discord:99999",
        "feat_nicoってついてるmp3を探して",
        source="discord",
        is_admin=True,
    )
    assert result["status"] == "completed"
    assert result["reply"] == "C:\\Music\\track_feat_nico.mp3"
    # Direct CLI result is returned immediately without a second Front Brain LLM round.
    assert len(calls_log) == 1


def test_web_propose_development_job_remains_proposed_for_approval(monkeypatch):
    coding_jobs.ensure_schema()
    calls_log = []
    _stub_front_brain(monkeypatch, calls_log)

    with patch.object(coding_jobs, "wait_for_job", side_effect=AssertionError("wait_for_job should not be called for web")):
        result = conversation_api.submit(
            "web-thread-1",
            "web-req-1",
            "feat_nicoってついてるmp3を探して",
            source="web",
            is_admin=True,
        )
    assert result["status"] == "completed"
    assert result["reply"] == "提案として置けました。"
    assert len(calls_log) == 2
    jobs = coding_jobs.list_jobs("web-thread-1")
    assert len(jobs) == 1
    assert jobs[0]["status"] == "proposed"
