from unittest.mock import Mock

from backend import development_models as models


def test_agy_windows_use_hydrogen_gemini_limits():
    raw = (
        "Gemini Models\tWeekly Limit Remaining\t96%\t2026-11-14T04:22:57Z\n"
        "Gemini Models\tFive Hour Limit Remaining\t98%\t2026-11-09T12:43:45Z\n"
        "Claude and GPT models\tFive Hour Limit Remaining\t0%\t2026-11-09T09:22:46Z\n"
    )
    assert models.parse_agy(raw) == {"antigravity_hydrogen": (98, 96), "antigravity_neon": (98, 96)}


def test_auto_routes_lightweight_and_ranks_available_windows(monkeypatch):
    def quota(five, weekly, available=True):
        return {"available": available, "five_hour": five, "weekly": weekly}

    items = {
        "claude_opus": quota(0, 100, False),
        "claude_sonnet": quota(0, 100, False),
        "codex_sol": quota(80, 54),
        "antigravity_hydrogen": quota(81, 54),
        "antigravity_neon": quota(81, 54),
    }
    monkeypatch.setattr(models, "usage", lambda: items)
    assert models.select("auto", "high")[:2] == ("antigravity_cli", "gemini-4-hydrogen-high")
    assert models.select("auto", "medium", lightweight=True)[:2] == ("antigravity_cli", "gemini-4-hydrogen-medium")
    assert models.select("antigravity_neon", "medium")[:2] == ("antigravity_cli", "gemini-4-neon-medium")
    assert models.select("codex_sol", "low")[:2] == ("codex", "gpt-6.2-sol")


def test_codex_reads_cli_account_and_inverts_used_percent(monkeypatch):
    client = Mock()
    client.request.side_effect = [
        {"account": {"type": "chatgpt"}},
        {"ordinaryUsageAllowed": True, "rateLimits": {"primary": {"usedPercent": 3}, "secondary": {"usedPercent": 73}}},
        {"data": [{"model": "gpt-6.1-sol"}]},
    ]
    monkeypatch.setattr(models.codex_brain, "RPC", Mock(return_value=client))
    assert models._codex() == {"codex_sol": (True, 97, 27, "gpt-6.1-sol")}
    client.close.assert_called_once()
    monkeypatch.setattr(models, "PROBES", {"codex": lambda: {"codex_sol": (True, 97, 27, "gpt-6.1-sol")}})
    quotas = models._collect(("codex",))
    provider, model, meta = models._choose("codex_sol", "high", False, quotas)
    assert (provider, model, meta["label"]) == ("codex", "gpt-6.1-sol", "Codex Sol 6.1")


def test_auto_falls_back_when_hydrogen_unavailable(monkeypatch):
    monkeypatch.setattr(models, "usage", lambda: {
        "antigravity_hydrogen": {"available": False, "five_hour": 0, "weekly": 0},
        "antigravity_neon": {"available": False, "five_hour": 0, "weekly": 0},
        "codex_sol": {"available": True, "five_hour": 80, "weekly": 80},
        "claude_opus": {"available": False, "five_hour": 0, "weekly": 0},
        "claude_sonnet": {"available": False, "five_hour": 0, "weekly": 0},
    })
    assert models.select("auto", "medium")[:2] == ("codex", "gpt-6.2-sol")
    assert models.select("auto", "medium", lightweight=True)[:2] == ("codex", "gpt-6.2-sol")


def test_claude_sonnet_shares_estimated_quota_and_is_selectable(monkeypatch):
    monkeypatch.setattr(models, "PROBES", {"claude_code": lambda: {"claude_opus": (True, 75, 90), "claude_sonnet": (True, 75, 90)}})
    monkeypatch.setattr(models.setup_store, "load", lambda: {})
    monkeypatch.setattr(models.brain_priority, "permitted", lambda provider, data: provider == "claude_code")
    monkeypatch.setattr(models.brain_priority, "target", lambda provider, data=None: {"configured": True})
    models.invalidate()
    quotas = models.usage()
    assert quotas["claude_sonnet"]["estimated"] is True
    assert quotas["claude_sonnet"]["available"] is True
    assert models.select("claude_sonnet", "medium")[:2] == ("claude_code", "sonnet")
    models.invalidate()


def test_development_request_accepts_all_configured_model_keys():
    from backend import coding_api

    for key in ("auto", *models.MODELS):
        req = coding_api.DevelopmentRequest(request_id="req-1", goal="check", model_key=key)
        assert req.model_key == key


def _usage_fixture(monkeypatch, clock):
    calls = []

    def probe():
        calls.append(clock[0])
        return {"codex_sol": (True, 100 - len(calls), 50)}

    monkeypatch.setattr(models, "PROBES", {"codex": probe})
    monkeypatch.setattr(models.setup_store, "load", lambda: {})
    monkeypatch.setattr(models.brain_priority, "permitted", lambda provider, data: True)
    monkeypatch.setattr(models.brain_priority, "target", lambda provider, data=None: {"configured": True})
    monkeypatch.setattr(models.time, "monotonic", lambda: clock[0])
    models.invalidate()
    return calls


def _wait_for_refresh():
    import time as real_time
    for _ in range(200):
        with models._lock:
            if not models._refreshing:
                return
        real_time.sleep(0.01)
    raise AssertionError("background refresh did not finish")


def test_usage_serves_stale_result_while_one_background_probe_refreshes(monkeypatch):
    clock = [1000.0]
    calls = _usage_fixture(monkeypatch, clock)
    assert models.usage()["codex_sol"]["five_hour"] == 99 and len(calls) == 1
    clock[0] += 30
    assert models.usage()["codex_sol"]["five_hour"] == 99 and len(calls) == 1  # fresh: no probe
    clock[0] += 120
    # Older than a minute: the caller gets the previous value at once; the probe runs behind it.
    assert models.usage()["codex_sol"]["five_hour"] == 99
    _wait_for_refresh()
    assert len(calls) == 2 and models.usage()["codex_sol"]["five_hour"] == 98
    clock[0] += models.STALE_SECONDS + 1
    assert models.usage()["codex_sol"]["five_hour"] == 97 and len(calls) == 3  # too old: wait for the probe
    models.invalidate()


def test_invalidation_discards_cache_and_any_probe_started_before_it(monkeypatch):
    clock = [1000.0]
    calls = _usage_fixture(monkeypatch, clock)
    models.usage()
    models.invalidate()
    assert models.usage()["codex_sol"]["five_hour"] == 98 and len(calls) == 2
    with models._lock:
        generation = models._generation
    models.invalidate()
    models._probe_and_store(("codex",), generation)  # a probe that began before the invalidation
    assert models._cache is None
    models.invalidate()


def test_stale_result_never_turns_a_request_down_without_asking_the_cli(monkeypatch):
    clock = [1000.0]
    state = {"five": 0}
    probes = []

    def probe():
        probes.append(clock[0])
        return {"codex_sol": (True, state["five"], 50)}

    _usage_fixture(monkeypatch, clock)
    monkeypatch.setattr(models, "PROBES", {"codex": probe})
    assert models.usage()["codex_sol"]["available"] is False  # the five-hour window is used up
    state["five"] = 80  # ...and has reset by the time of the next request
    clock[0] += 900
    with models._lock:
        models._refreshing = True  # as if a background refresh were still running: only the stale value is at hand
    assert models.select("codex_sol", "low")[:2] == ("codex", "gpt-6.2-sol")
    assert len(probes) == 2
    models.invalidate()
    with models._lock:
        models._refreshing = False


def test_auto_prefers_claude_sonnet_over_opus_when_tied(monkeypatch):
    monkeypatch.setattr(models, "usage", lambda: {
        "antigravity_hydrogen": {"available": False, "five_hour": 0, "weekly": 0},
        "antigravity_neon": {"available": False, "five_hour": 0, "weekly": 0},
        "codex_sol": {"available": False, "five_hour": 0, "weekly": 0},
        "claude_opus": {"available": True, "five_hour": 100, "weekly": 100},
        "claude_sonnet": {"available": True, "five_hour": 100, "weekly": 100},
    })
    provider, model, selection = models.select("auto", "medium")
    assert provider == "claude_code"
    assert model == "sonnet"
    assert selection["model_key"] == "claude_sonnet"


def test_provider_usage_returns_four_providers_with_deepseek_cost(monkeypatch):
    monkeypatch.setattr(models.setup_store, "load", lambda: {})
    monkeypatch.setattr(models.brain_priority, "permitted", lambda provider, data: provider in {"antigravity_cli", "deepseek"})
    monkeypatch.setattr(models.brain_priority, "target", lambda provider, data=None: {"configured": provider != "codex"})
    monkeypatch.setattr(models.deepseek_usage, "today_summary", lambda: {"cost_usd": 0.042, "requests": 3, "tokens": 1000, "day": "2026-11-23"})

    quotas = {
        "antigravity_hydrogen": {"authenticated": True, "available": True, "five_hour": 95, "weekly": 80, "estimated": False},
        "antigravity_neon": {"authenticated": True, "available": True, "five_hour": 95, "weekly": 80, "estimated": False},
        "codex_sol": {"authenticated": None, "available": False, "five_hour": None, "weekly": None, "estimated": False},
        "claude_sonnet": {"authenticated": True, "available": False, "five_hour": 0, "weekly": 70, "estimated": True},
        "claude_opus": {"authenticated": True, "available": False, "five_hour": 0, "weekly": 70, "estimated": True},
    }
    providers = models.provider_usage(quotas)
    assert [item["key"] for item in providers] == ["antigravity_cli", "codex", "claude_code", "deepseek"]
    assert providers[0]["five_hour"] == 95 and providers[0]["weekly"] == 80
    assert providers[1]["configured"] is False
    assert providers[2]["estimated"] is True and providers[2]["permitted"] is False
    assert providers[3]["today_cost_usd"] == 0.042 and providers[3]["available"] is True
