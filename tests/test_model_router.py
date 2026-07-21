from backend import model_router
from backend.lmstudio_client import LMStudioError


def _reply(content: str):
    return {"role": "assistant", "content": content}


def test_ai_router_keeps_casual_message_on_chat(monkeypatch) -> None:
    monkeypatch.setattr(
        model_router,
        "chat_completion",
        lambda *args, **kwargs: _reply('{"route":"chat","confidence":0.97,"reason":"感想のみ"}'),
    )

    route = model_router.choose("会話しやすさはかなり改善した")

    assert route["kind"] == "chat"
    assert route["router_source"] == "ai"
    assert route["router_confidence"] == 0.97


def test_ai_router_sends_reasoning_request_to_agent(monkeypatch) -> None:
    monkeypatch.setattr(
        model_router,
        "chat_completion",
        lambda *args, **kwargs: _reply('{"route":"agent","confidence":0.91,"reason":"設計評価が必要"}'),
    )

    route = model_router.choose("このエージェント設計を評価して")

    assert route["kind"] == "agent"
    assert "ai_router:agent" in route["reasons"]


def test_ai_router_sends_context_request_to_agent(monkeypatch) -> None:
    monkeypatch.setattr(
        model_router,
        "chat_completion",
        lambda *args, **kwargs: _reply('{"route":"tool","confidence":0.94,"reason":"予定取得が必要"}'),
    )

    route = model_router.choose("明日の予定を教えて")

    assert route["kind"] == "agent"
    assert "ai_router:tool" in route["reasons"]


def test_router_accepts_json_code_fence(monkeypatch) -> None:
    monkeypatch.setattr(
        model_router,
        "chat_completion",
        lambda *args, **kwargs: _reply('```json\n{"route":"chat","confidence":1,"reason":"雑談"}\n```'),
    )

    assert model_router.choose("やっほー")["kind"] == "chat"


def test_malformed_router_output_uses_fallback(monkeypatch) -> None:
    monkeypatch.setattr(model_router, "chat_completion", lambda *args, **kwargs: _reply("CHATで十分です"))

    route = model_router.choose("PETITの改善案を考えて")

    assert route["kind"] == "agent"
    assert route["router_source"] == "fallback"


def test_router_connection_failure_uses_fallback(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise LMStudioError("offline")

    monkeypatch.setattr(model_router, "chat_completion", fail)

    route = model_router.choose("今日は問題ないよ")

    assert route["kind"] == "chat"
    assert route["router_source"] == "fallback"
