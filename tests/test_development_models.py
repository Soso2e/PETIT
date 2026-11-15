from unittest.mock import Mock

from backend import development_models as models


def test_agy_windows_use_hydrogen_gemini_limits():
    raw = (
        "Gemini Models\tWeekly Limit Remaining\t96%\t2026-11-14T04:22:57Z\n"
        "Gemini Models\tFive Hour Limit Remaining\t98%\t2026-11-09T12:43:45Z\n"
        "Claude and GPT models\tFive Hour Limit Remaining\t0%\t2026-11-09T09:22:46Z\n"
    )
    assert models.parse_agy(raw) == {"antigravity_hydrogen": (98, 96), "gemini_flash": (98, 96)}


def test_auto_routes_lightweight_and_ranks_available_windows(monkeypatch):
    def quota(five, weekly, available=True):
        return {"available": available, "five_hour": five, "weekly": weekly}

    items = {
        "claude_opus": quota(0, 100, False),
        "codex_sol": quota(80, 54),
        "antigravity_hydrogen": quota(81, 54),
        "gemini_flash": quota(98, 96),
    }
    monkeypatch.setattr(models, "usage", lambda: items)
    assert models.select("auto", "high")[:2] == ("antigravity_cli", "gemini-4-hydrogen-high")
    assert models.select("auto", "medium", lightweight=True)[:2] == ("antigravity_cli", "gemini-4-hydrogen-medium")
    assert models.select("codex_sol", "low")[:2] == ("codex", "gpt-6.1-sol")


def test_codex_reads_cli_account_and_inverts_used_percent(monkeypatch):
    client = Mock()
    client.request.side_effect = [
        {"account": {"type": "chatgpt"}},
        {"ordinaryUsageAllowed": True, "rateLimits": {"primary": {"usedPercent": 3}, "secondary": {"usedPercent": 73}}},
    ]
    monkeypatch.setattr(models.codex_brain, "RPC", Mock(return_value=client))
    assert models._codex() == {"codex_sol": (True, 97, 27)}
    client.close.assert_called_once()


def test_auto_falls_back_when_hydrogen_unavailable(monkeypatch):
    monkeypatch.setattr(models, "usage", lambda: {
        "antigravity_hydrogen": {"available": False, "five_hour": 0, "weekly": 0},
        "gemini_flash": {"available": True, "five_hour": 90, "weekly": 90},
        "codex_sol": {"available": True, "five_hour": 80, "weekly": 80},
        "claude_opus": {"available": False, "five_hour": 0, "weekly": 0},
    })
    assert models.select("auto", "medium")[:2] == ("codex", "gpt-6.1-sol")
    assert models.select("auto", "medium", lightweight=True)[:2] == ("antigravity_cli", "gemini-3.8-flash-medium")
