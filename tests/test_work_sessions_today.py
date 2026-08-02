from datetime import datetime, timedelta, timezone

from backend import work_sessions


def test_today_summary_counts_active_session(tmp_path, monkeypatch):
    monkeypatch.setattr(work_sessions.db, "DB_PATH", tmp_path / "test.db")
    start = datetime(2026, 8, 2, 0, 0, tzinfo=timezone.utc)
    work_sessions.start_session("s1", "PETIT開発", project_id="PETIT", now=start)
    summary = work_sessions.today_summary(now=start + timedelta(minutes=45))
    assert summary["total_seconds"] == 45 * 60
    assert summary["projects"][0]["project"] == "PETIT"
    assert summary["active"]["session_id"] == "s1"


def test_today_summary_excludes_pause_time(tmp_path, monkeypatch):
    monkeypatch.setattr(work_sessions.db, "DB_PATH", tmp_path / "test.db")
    start = datetime(2026, 8, 2, 1, 0, tzinfo=timezone.utc)
    work_sessions.start_session("s1", "Maya", project_id="Maya", now=start)
    work_sessions.pause_session("s1", now=start + timedelta(minutes=20))
    work_sessions.resume_session("s1", now=start + timedelta(minutes=50))
    work_sessions.end_session("s1", now=start + timedelta(minutes=80))
    summary = work_sessions.today_summary(now=start + timedelta(minutes=90))
    assert summary["total_seconds"] == 50 * 60
