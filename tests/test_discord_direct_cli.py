import json
from unittest.mock import patch

from tests.test_setup_integrations import isolated  # noqa: F401 - autouse isolation
from backend import brain, coding_jobs, conversation_api, development_models, development_threads, lmstudio_client, tools
from backend.channels.discord import relay


def _stub_front_brain(monkeypatch, calls_log, *, dev_thread_id: str | None = None):
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
            args = {"repository": "", "goal": "feat_nico を含む mp3 を探して"}
            if dev_thread_id:
                args["dev_thread_id"] = dev_thread_id
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "propose_development_job",
                            "arguments": json.dumps(args),
                        },
                    }
                ],
            }
        return {"role": "assistant", "content": "開発ジョブを投げました。終わったらお知らせします。"}

    monkeypatch.setattr(lmstudio_client, "chat_completion", fake_chat)


def test_discord_propose_development_job_queues_async_and_returns_dev_thread_id(monkeypatch):
    coding_jobs.ensure_schema()
    calls_log = []
    _stub_front_brain(monkeypatch, calls_log)

    with patch.object(coding_jobs, "wait_for_job", side_effect=AssertionError("wait_for_job should not block Discord")):
        result = conversation_api.submit(
            "discord:12345",
            "discord:99999",
            "feat_nicoってついてるmp3を探して",
            source="discord",
            is_admin=True,
            discord_author_id="777888",
            discord_guild_id="555666",
        )

    assert result["status"] == "completed"
    # Front Brain runs 2 rounds (tool call -> immediate reply) without blocking.
    assert len(calls_log) == 2
    job_id = coding_jobs.turn_job("discord:99999")
    assert job_id is not None
    job = coding_jobs.get(job_id)
    assert job["status"] == "queued"
    assert job["thread_id"] != "discord:12345"
    dev_thread_id = job["thread_id"]
    assert dev_thread_id in result["reply"]
    assert job_id in result["reply"]

    # Continue in the same dev_thread_id on a follow-up Discord message.
    calls_log_2 = []
    _stub_front_brain(monkeypatch, calls_log_2, dev_thread_id=dev_thread_id)
    result2 = conversation_api.submit(
        "discord:12345",
        "discord:100000",
        "続きで別の条件も探して",
        source="discord",
        is_admin=True,
        discord_author_id="777888",
        discord_guild_id="555666",
    )
    assert result2["status"] == "completed"
    job_id_2 = coding_jobs.turn_job("discord:100000")
    assert job_id_2 is not None and job_id_2 != job_id
    assert coding_jobs.get(job_id_2)["thread_id"] == dev_thread_id

    # DeepSeek can inspect threads and status by dev_thread_id.
    listed = json.loads(tools.dispatch("list_development_threads", {"limit": 5}))
    assert any(t["dev_thread_id"] == dev_thread_id for t in listed["threads"])
    status_by_thread = json.loads(tools.dispatch("get_coding_task_status", {"dev_thread_id": dev_thread_id}))
    assert status_by_thread["dev_thread_id"] == dev_thread_id
    assert status_by_thread["job_count"] == 2


def test_discord_coding_notice_enqueue_claim_and_report(monkeypatch):
    coding_jobs.ensure_schema()
    calls_log = []
    _stub_front_brain(monkeypatch, calls_log)

    conversation_api.submit(
        "discord:12345",
        "discord:88888",
        "feat_nicoってついてるmp3を探して",
        source="discord",
        is_admin=True,
        discord_author_id="777888",
        discord_guild_id="555666",
    )
    job_id = coding_jobs.turn_job("discord:88888")
    assert job_id is not None
    dev_thread_id = coding_jobs.get(job_id)["thread_id"]

    coding_jobs.finish(job_id, "ready_for_review", summary="C:\\Music\\track_feat_nico.mp3")
    claimed = coding_jobs.claim_discord_notices()
    assert len(claimed) == 1
    notice = claimed[0]
    assert notice["job_id"] == job_id
    assert notice["dev_thread_id"] == dev_thread_id
    assert notice["channel_id"] == "12345"
    assert notice["author_id"] == "777888"
    assert notice["job_status"] == "ready_for_review"

    text = relay.coding_notice_text(notice)
    assert "<@777888>" in text
    assert dev_thread_id in text
    assert job_id in text
    assert "track_feat_nico.mp3" in text

    # Already claimed, so a second claim returns empty.
    assert coding_jobs.claim_discord_notices() == []
    assert coding_jobs.report_discord_notice(notice["notice_id"], "sent") is True


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
    assert result["reply"] == "開発ジョブを投げました。終わったらお知らせします。"
    assert len(calls_log) == 2
    jobs = coding_jobs.list_jobs("web-thread-1")
    assert len(jobs) == 1
    assert jobs[0]["status"] == "proposed"
