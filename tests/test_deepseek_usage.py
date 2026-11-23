from datetime import datetime, timezone

import pytest

from backend import config, db, deepseek_usage, lmstudio_client, request_context


def test_calculate_cost_usd_peak_and_off_peak():
    off_peak = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)  # Sunday -> off-peak
    peak = datetime(2026, 11, 23, 2, 0, tzinfo=timezone.utc)  # Monday 02:00 UTC -> peak
    usage = {
        "prompt_tokens": 1_000_000,
        "prompt_cache_hit_tokens": 400_000,
        "prompt_cache_miss_tokens": 600_000,
        "completion_tokens": 100_000,
    }
    # flash off-peak: 0.4*0.003 + 0.6*0.15 + 0.1*0.60 = 0.0012 + 0.09 + 0.06 = 0.1512
    assert deepseek_usage.calculate_cost_usd(usage, model="deepseek-flash", now=off_peak) == pytest.approx(0.1512)
    # flash peak: 2x off-peak = 0.3024
    assert deepseek_usage.calculate_cost_usd(usage, model="deepseek-flash", now=peak) == pytest.approx(0.3024)
    # pro off-peak: 0.4*0.022 + 0.6*0.66 + 0.1*1.98 = 0.0088 + 0.396 + 0.198 = 0.6028
    assert deepseek_usage.calculate_cost_usd(usage, model="deepseek-v4-pro", now=off_peak) == pytest.approx(0.6028)


def test_record_and_today_summary_filters_by_day_and_skips_guild_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(config, "DAILY_INDEX_TIMEZONE", "Asia/Tokyo")
    db.init_db()

    yesterday = datetime(2026, 11, 22, 10, 0, tzinfo=timezone.utc)
    today = datetime(2026, 11, 23, 5, 0, tzinfo=timezone.utc)
    usage = {
        "prompt_tokens": 1000,
        "prompt_cache_hit_tokens": 500,
        "prompt_cache_miss_tokens": 500,
        "completion_tokens": 200,
    }

    deepseek_usage.record(usage, model="deepseek-flash", route="chat", now=yesterday)
    deepseek_usage.record(usage, model="deepseek-flash", route="chat", now=today)
    with request_context.guild_mode(guild_id="g1"):
        deepseek_usage.record(usage, model="deepseek-flash", route="guild", now=today)

    summary = deepseek_usage.today_summary(now=today)
    assert summary["day"] == "2026-11-23"
    assert summary["requests"] == 1
    assert summary["tokens"] == 1200
    assert summary["cost_usd"] > 0


def test_lmstudio_client_records_deepseek_usage_without_observe_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(config, "DAILY_INDEX_TIMEZONE", "UTC")
    db.init_db()

    lmstudio_client._record_usage(
        {"usage": {"prompt_tokens": 200, "completion_tokens": 50}},
        {"provider": "deepseek", "model": "deepseek-flash", "profile": "deepseek"},
        route="title",
    )
    summary = deepseek_usage.today_summary()
    assert summary["requests"] == 1
    assert summary["tokens"] == 250
