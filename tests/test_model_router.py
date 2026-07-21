from backend import model_router
from backend.lmstudio_client import LMStudioError


def _reply(content: str):
    return {"role": "assistant", "content": content}


def test_one_pass_router_generates_chat_reply(monkeypatch) -> None:
    prefetched: list[tuple[str, str]] = []
    monkeypatch.setattr(
        model_router,
        "chat_completion",
        lambda *args, **kwargs: _reply(
            '{"type":"reply","reply":"やっほー。どうした？","confidence":0.98}'
        ),
    )
    monkeypatch.setattr(
        model_router,
        "set_prefetched_chat",
        lambda user, reply: prefetched.append((user, reply)),
    )

    route = model_router.choose("やっほー")

    assert route["kind"] == "chat"
    assert route["prefetched_reply"] is True
    assert route["router_confidence"] == 0.98
    assert prefetched == [("やっほー", "やっほー。どうした？")]


def test_one_pass_router_requests_agent(monkeypatch) -> None:
    monkeypatch.setattr(
        model_router,
        "chat_completion",
        lambda *args, **kwargs: _reply(
            '{"type":"agent","reason":"設計評価が必要","confidence":0.91}'
        ),
    )

    route = model_router.choose("このエージェント設計を評価して")

    assert route["kind"] == "agent"
    assert "ai_router:agent" in route["reasons"]


def test_one_pass_router_returns_tool_suggestions(monkeypatch) -> None:
    monkeypatch.setattr(
        model_router,
        "chat_completion",
        lambda *args, **kwargs: _reply(
            '{"type":"tool","tools":["get_schedule"],"reason":"予定取得が必要","confidence":0.94}'
        ),
    )

    route = model_router.choose("明日の予定を教えて")

    assert route["kind"] == "agent"
    assert route["suggested_tools"] == ["get_schedule"]
    assert "ai_router:tool" in route["reasons"]


def test_router_accepts_json_code_fence(monkeypatch) -> None:
    monkeypatch.setattr(
        model_router,
        "chat_completion",
        lambda *args, **kwargs: _reply(
            '```json\n{"type":"reply","reply":"了解。","confidence":1}\n```'
        ),
    )
    monkeypatch.setattr(model_router, "set_prefetched_chat", lambda *args: None)

    assert model_router.choose("了解")['kind'] == "chat"


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
