"""#411: DeepSeek first as a toggle, and CLI work handed off on the Turn ledger."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.test_setup_integrations import isolated  # noqa: F401 - autouse isolation
from backend import (brain, brain_priority, claude_agent, claude_code_brain as cc, conversation_api as api,
                     conversation_store as store, db, delegations, lmstudio_client, request_context, setup_api,
                     setup_store, tools)


def tool_call(name, arguments, call_id="c1"):
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}]}


@pytest.fixture
def ready(monkeypatch):
    monkeypatch.setattr(cc, "executable", lambda: "claude")
    monkeypatch.setattr(cc, "require_production_permission", lambda: None)
    setup_store.update({"brain_enabled": True, "brain_transport": "mixed", "priority": ["claude_code", "deepseek"],
                        "connected": ["deepseek", "claude_code"], "paid_allowed": ["deepseek"],
                        "claude_code_enabled": True, "front_brain_deepseek": True, "claude_code_model": "opus"},
                       {"deepseek_key": "test-key"})


@pytest.fixture
def model(monkeypatch):
    """Scripted DeepSeek; records the provider and Tools each call received."""
    calls, replies = [], []

    def completion(messages, tools=None, target_override=None, **_):
        calls.append({"provider": target_override["provider"], "tools": [x["function"]["name"] for x in tools or []],
                      "system": messages[0]["content"]})
        return replies.pop(0)
    monkeypatch.setattr(lmstudio_client, "chat_completion", completion)
    return calls, replies


def submit(thread="t1", request="r1", message="メモを整理して"):
    return api.submit(thread, request, message, is_admin=True)


def delegate_turn(replies):
    replies.extend([tool_call("delegate_to_agent", {"goal": "メモを整理する"}), {"role": "assistant", "content": "任せたよ"}])
    return submit()


def work_row():
    with db.get_connection() as connection:
        return dict(connection.execute("SELECT * FROM delegations ORDER BY created_at LIMIT 1").fetchone())


def reports():
    with db.get_connection() as connection:
        return [dict(r) for r in connection.execute(
            "SELECT user_text,assistant_text FROM conversations WHERE session_id='t1' AND source='delegate' ORDER BY id")]


def fake_agent(monkeypatch, reply="整理しました"):
    seen = {}

    def run(request_id, target, *, messages=None, used_tools=None):
        seen.update(target=target, message=json.loads(store.load_turn(request_id)["input_json"] or "{}").get("message"))
        return store.finish(request_id, {"reply": reply, "used_tools": []})
    monkeypatch.setattr(claude_agent, "run", run)
    return seen


# --- toggle ---------------------------------------------------------------------------

def test_toggle_moves_deepseek_first_without_rewriting_priority(ready, model):
    calls, replies = model
    replies.append({"role": "assistant", "content": "おはよう"})
    assert submit(message="おはよう")["reply"] == "おはよう"
    assert calls[0]["provider"] == "deepseek" and len(calls) == 1
    assert setup_store.load()["priority"] == ["claude_code", "deepseek"]


def test_toggle_off_keeps_the_saved_order():
    data = {"priority": ["claude_code", "deepseek"], "brain_enabled": True, "brain_transport": "mixed"}
    assert delegations.front_order({**data, "front_brain_deepseek": False}) == ["claude_code", "deepseek"]
    assert delegations.front_order({**data, "front_brain_deepseek": True}) == ["deepseek", "claude_code"]


def test_cli_only_ignores_the_toggle():
    data = {"priority": ["claude_code", "deepseek"], "brain_enabled": True, "brain_transport": "cli_only", "front_brain_deepseek": True}
    assert delegations.front_order(data) == ["claude_code", "deepseek"]


def test_first_call_has_routine_writes_and_hand_off_but_no_mail_body(ready, model):
    calls, replies = model
    setup_store.update({"connected": ["deepseek", "claude_code", "gmail"]}, {"google_tokens": {"scopes": []}})
    replies.append({"role": "assistant", "content": "はい"})
    submit()
    assert {"start_work_session", "create_task", "record_past_work", "delegate_to_agent",
            "propose_development_job", "list_coding_repositories"} <= set(calls[0]["tools"])
    assert "add_schedule" not in calls[0]["tools"]
    assert "gmail_get_message:" not in calls[0]["system"] and "gmail_search:" in calls[0]["system"]
    assert "delegate_to_agentでCLIに任せる" in calls[0]["system"]
    # Repository and Home-file work is handed off, so the Front index omits those Tools and the Home hint.
    for name in ("open_worktree", "commit_worktree", "delegate_coding_task", "write_home_file"):
        assert name + ":" not in calls[0]["system"]
    assert "read_home_file:" in calls[0]["system"] and "*_home_file Tool" not in calls[0]["system"]


def test_toggle_off_has_no_hand_off_tool(ready, model):
    calls, replies = model
    setup_store.update({"front_brain_deepseek": False, "priority": ["deepseek"]})
    replies.append({"role": "assistant", "content": "はい"})
    submit()
    assert "delegate_to_agent" not in calls[0]["tools"] and "delegate_to_agent" not in calls[0]["system"]
    assert "start_work_session" not in calls[0]["tools"]
    assert "propose_development_job:" in calls[0]["system"] and "*_home_file Tool" in calls[0]["system"]
    assert "open_worktree:" not in calls[0]["system"]


def client():
    app = FastAPI()
    app.include_router(setup_api.router)
    app.dependency_overrides[setup_api._admin] = lambda: None
    return TestClient(app)


def test_settings_refuse_the_toggle_without_consent(ready):
    setup_store.update({"front_brain_deepseek": False, "paid_allowed": []})
    assert client().put("/api/setup/config", json={"front_brain_deepseek": True}).status_code == 400
    assert setup_store.load()["front_brain_deepseek"] is False
    setup_store.update({"paid_allowed": ["deepseek"]})
    response = client().put("/api/setup/config", json={"front_brain_deepseek": True, "delegate_claude_model": "haiku",
                                                       "delegate_priority": ["codex", "claude_code"]})
    assert response.status_code == 200 and setup_store.load()["delegate_priority"] == ["codex", "claude_code"]


@pytest.mark.parametrize("body", [{"delegate_claude_model": "opus"}, {"delegate_priority": ["antigravity_cli"]},
                                  {"delegate_priority": []}, {"delegate_priority": ["codex", "codex"]}])
def test_settings_refuse_bad_delegate_values(ready, body):
    assert client().put("/api/setup/config", json=body).status_code in {400, 422}


# --- hand-off -------------------------------------------------------------------------

def test_hand_off_answers_at_once_and_says_so(ready, model):
    _, replies = model
    result = delegate_turn(replies)
    row = work_row()
    assert result["status"] == "completed" and result["reply"].startswith("任せたよ")
    assert "Claude Code（Sonnet）に任せました" in result["reply"]
    assert store.load_turn(row["work_request_id"])["status"] == "queued"
    assert store.thread(row["work_thread_id"])["source"] == "delegate"
    assert row["parent_request_id"] == "r1" and row["provider"] == "claude_code"
    assert store.receipt("r1", "c1")["status"] == "applied"


def test_work_request_carries_original_words_written_by_core(ready, model, monkeypatch):
    _, replies = model
    delegate_turn(replies)
    seen = fake_agent(monkeypatch)
    assert delegations.tick() is True
    assert "メモを整理して" in seen["message"] and "メモを整理する" in seen["message"]


def test_delegated_claude_uses_the_low_consumption_model_not_the_chat_one(ready, model, monkeypatch):
    _, replies = model
    setup_store.update({"delegate_claude_model": "haiku"})
    delegate_turn(replies)
    seen = fake_agent(monkeypatch)
    delegations.tick()
    assert seen["target"]["model"] == "haiku" and setup_store.load()["claude_code_model"] == "opus"


def test_chat_stays_free_while_work_is_pending(ready, model):
    _, replies = model
    delegate_turn(replies)
    replies.append({"role": "assistant", "content": "次の話"})
    assert submit(request="r2", message="ところで")["reply"] == "次の話"
    assert store.load_turn(work_row()["work_request_id"])["status"] == "queued"


def test_one_hand_off_per_turn_and_no_recursion(ready, model):
    _, replies = model
    replies.extend([tool_call("delegate_to_agent", {"goal": "A"}, "c1"), tool_call("delegate_to_agent", {"goal": "B"}, "c2"),
                    {"role": "assistant", "content": "任せたよ"}])
    submit()
    with db.get_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM delegations").fetchone()[0] == 1
    row = work_row()
    with request_context.bind(request_id=row["work_request_id"], session_id=row["work_thread_id"], is_admin=True):
        assert not delegations.tool_available("delegate_to_agent", setup_store.load(), local_only=False)
        with pytest.raises(ValueError):
            delegations.start("再帰")


def test_no_cli_available_is_refused(ready):
    setup_store.update({"claude_code_enabled": False, "connected": ["deepseek"]})
    with request_context.bind(request_id="x", session_id="t9", is_admin=True):
        with pytest.raises(ValueError, match="任せられるCLI"):
            delegations.start("作業")


def test_local_only_never_hands_off(ready):
    assert not delegations.tool_available("delegate_to_agent", setup_store.load(), local_only=True)


def test_work_threads_stay_out_of_the_thread_list(ready, model):
    _, replies = model
    delegate_turn(replies)
    assert [x["id"] for x in store.list_threads()] == ["t1"]


# --- report ---------------------------------------------------------------------------

def test_finished_work_is_reported_once_separating_core_facts_from_cli_claims(ready, model, monkeypatch):
    _, replies = model
    delegate_turn(replies)
    fake_agent(monkeypatch, reply="全部終わりました")
    delegations.tick()
    delegations.reconcile()
    saved = reports()
    assert len(saved) == 1 and saved[0]["user_text"] == ""
    text = saved[0]["assistant_text"]
    assert "完了" in text and "Coreで確認" in text and "CLIの報告（未検証）:\n全部終わりました" in text
    assert all(m["content"] for m in store.history("t1"))  # the empty user side does not reach the model


def test_long_report_is_cut_for_the_parent_thread(ready, model, monkeypatch):
    _, replies = model
    delegate_turn(replies)
    fake_agent(monkeypatch, reply="あ" * 9000)
    delegations.tick()
    report = reports()[0]["assistant_text"]
    assert len(report) < delegations.REPORT_CHARS + 100 and "省略" in report


def test_failed_work_reports_the_reason_and_no_success_claim(ready, model, monkeypatch):
    _, replies = model
    delegate_turn(replies)

    def boom(*_args, **_kwargs):
        raise lmstudio_client.LMStudioError("CLIが落ちました")
    monkeypatch.setattr(claude_agent, "run", boom)
    delegations.tick()
    report = reports()[0]["assistant_text"]
    assert "失敗" in report and "CLIの報告" not in report


def test_outdated_cli_is_named_in_the_report(ready, model, monkeypatch):
    _, replies = model
    delegate_turn(replies)
    monkeypatch.setattr(claude_agent, "invoke", lambda *a, **k: (1, "", "error: unknown option '--restricted'"))
    delegations.tick()
    report = reports()[0]["assistant_text"]
    assert "失敗" in report and "claude update" in report


def test_restart_reports_interruption_and_does_not_rerun(ready, model, monkeypatch):
    _, replies = model
    delegate_turn(replies)
    store.recover()
    called = []
    monkeypatch.setattr(claude_agent, "run", lambda *a, **k: called.append(1))
    assert delegations.tick() is False and not called
    assert "中断" in reports()[0]["assistant_text"]


def test_cancel_stops_queued_work_and_reports(ready, model, monkeypatch):
    _, replies = model
    delegate_turn(replies)
    delegations.cancel(work_row()["id"])
    assert store.load_turn(work_row()["work_request_id"])["status"] == "cancelled"
    called = []
    monkeypatch.setattr(claude_agent, "run", lambda *a, **k: called.append(1))
    assert delegations.tick() is False and not called
    assert "取消" in reports()[0]["assistant_text"]


def test_one_job_at_a_time(ready, model):
    _, replies = model
    delegate_turn(replies)
    replies.extend([tool_call("delegate_to_agent", {"goal": "二つ目"}), {"role": "assistant", "content": "任せたよ"}])
    submit(request="r2", message="別の作業")
    store.claim(delegations.next_queued())
    assert delegations.next_queued() is None


# --- approval in the parent Thread ------------------------------------------------------

def waiting_agent(monkeypatch, after):
    def run(request_id, target, *, messages=None, used_tools=None):
        if messages is None:
            store.propose(request_id, {"id": "a1", "function": {"name": "add_schedule"}},
                          {"title": "歯医者", "start_time": "2026-11-10T10:00"})
            store.save_messages(request_id, [])
            return store.finish(request_id, {"reply": "確認してください", "used_tools": []}, status="waiting_approval")
        after.append(request_id)
        return store.finish(request_id, {"reply": "登録しました", "used_tools": []})
    monkeypatch.setattr(claude_agent, "run", run)


def test_approval_appears_in_the_parent_and_resumes_off_the_request(ready, model, monkeypatch):
    _, replies = model
    delegate_turn(replies)
    after = []
    waiting_agent(monkeypatch, after)
    delegations.tick()
    row = work_row()
    saved = reports()
    assert len(saved) == 1 and "確認待ち" in saved[0]["assistant_text"] and "add_schedule" in saved[0]["assistant_text"]
    pending = store.snapshot("t1")["pending_actions"]
    assert [x["name"] for x in pending] == ["add_schedule"]
    assert delegations.listing("t1")[0]["pending_actions"][0]["name"] == "add_schedule"

    submitted = []
    monkeypatch.setattr(delegations._resume_pool, "submit", lambda fn: submitted.append(fn))
    monkeypatch.setattr(brain, "execute", lambda *a, **k: store.encode({"created": True}))
    answer = api.decide(pending[0]["approval_id"], True)
    assert submitted and not after and answer["status"] == "running" and "続き" in answer["reply"]
    submitted[0]()
    assert after == [row["work_request_id"]] and store.load_turn(row["work_request_id"])["status"] == "completed"
    delegations.reconcile()
    assert "完了" in reports()[-1]["assistant_text"]


def test_expired_approval_stops_the_work_and_is_reported(ready, model, monkeypatch):
    _, replies = model
    delegate_turn(replies)
    waiting_agent(monkeypatch, [])
    delegations.tick()
    with db.get_connection() as connection:
        connection.execute("UPDATE turn_approvals SET expires_at=0")
    delegations.reconcile()
    assert store.load_turn(work_row()["work_request_id"])["status"] == "cancelled"
    assert "取消" in reports()[-1]["assistant_text"]


def test_tools_are_registered_with_their_risks():
    assert {"delegate_to_agent", "get_delegation_status", "cancel_delegation"} <= brain.PUBLIC_TOOLS
    assert tools.risk_for("delegate_to_agent") == "low_risk_write" and not tools.requires_confirmation("delegate_to_agent")
    assert tools.risk_for("get_delegation_status") == "safe_read"
    assert brain_priority.delegate_target("claude_code", setup_store.load())["_delegate"] is True
