from backend import lmstudio_client


def test_prefetched_chat_reply_skips_http(monkeypatch) -> None:
    called = False

    def should_not_call(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("HTTP should not be called")

    monkeypatch.setattr(lmstudio_client, "_post_completion", should_not_call)

    with lmstudio_client.observe_turn() as metrics:
        lmstudio_client.set_prefetched_chat("やっほー", "やっほー。どうした？")
        response = lmstudio_client.chat_completion(
            [
                {"role": "system", "content": "あなたはPETIT。"},
                {"role": "user", "content": "やっほー"},
            ],
            route="chat",
        )

    assert response["content"] == "やっほー。どうした？"
    assert response["_prefetched_reply"] is True
    assert metrics["llm_calls"] == 0
    assert called is False


def test_prefetched_reply_is_consumed_once(monkeypatch) -> None:
    monkeypatch.setattr(
        lmstudio_client,
        "_post_completion",
        lambda **kwargs: {
            "choices": [
                {"message": {"role": "assistant", "content": "二回目"}, "finish_reason": "stop"}
            ]
        },
    )

    messages = [{"role": "user", "content": "やっほー"}]
    with lmstudio_client.observe_turn() as metrics:
        lmstudio_client.set_prefetched_chat("やっほー", "一回目")
        first = lmstudio_client.chat_completion(messages, route="chat")
        second = lmstudio_client.chat_completion(messages, route="chat")

    assert first["content"] == "一回目"
    assert second["content"] == "二回目"
    assert metrics["llm_calls"] == 1
