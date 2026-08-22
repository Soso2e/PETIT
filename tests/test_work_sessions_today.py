from datetime import datetime, timedelta, timezone

from backend import work_sessions


def test_today_summary_counts_active_session(tmp_path, monkeypatch):
    monkeypatch.setattr(work_sessions.db.config, "DB_PATH", tmp_path / "test.db")
    start = datetime(2026, 8, 2, 0, 0, tzinfo=timezone.utc)
    work_sessions.start_session(
        "s1", "PETIT開発", task_id="notion-task-1", project_id="PETIT", now=start
    )
    summary = work_sessions.today_summary(now=start + timedelta(minutes=45))
    assert summary["total_seconds"] == 45 * 60
    assert summary["projects"][0]["project"] == "PETIT"
    assert summary["tasks"] == [{
        "task_id": "notion-task-1",
        "task": "PETIT開発",
        "project_id": "PETIT",
        "elapsed_seconds": 45 * 60,
    }]
    assert summary["active"]["session_id"] == "s1"
    assert summary["active"]["elapsed_seconds"] == 45 * 60


def test_today_summary_excludes_pause_time(tmp_path, monkeypatch):
    monkeypatch.setattr(work_sessions.db.config, "DB_PATH", tmp_path / "test.db")
    start = datetime(2026, 8, 2, 1, 0, tzinfo=timezone.utc)
    work_sessions.start_session("s1", "Maya", project_id="Maya", now=start)
    work_sessions.pause_session("s1", now=start + timedelta(minutes=20))
    work_sessions.resume_session("s1", now=start + timedelta(minutes=50))
    work_sessions.end_session("s1", now=start + timedelta(minutes=80))
    summary = work_sessions.today_summary(now=start + timedelta(minutes=90))
    assert summary["total_seconds"] == 50 * 60


def test_period_summary_groups_repeated_sessions_by_task(tmp_path, monkeypatch):
    monkeypatch.setattr(work_sessions.db.config, "DB_PATH", tmp_path / "test.db")
    start = datetime(2026, 8, 1, 15, 0, tzinfo=timezone.utc)  # 2026-08-02 00:00 JST
    work_sessions.start_session("s1", "PETIT開発", task_id="task-1", project_id="PETIT", now=start)
    work_sessions.end_session("s1", now=start + timedelta(minutes=30))
    work_sessions.start_session(
        "s2", "PETIT開発", task_id="task-1", project_id="PETIT", now=start + timedelta(days=1)
    )
    work_sessions.end_session("s2", now=start + timedelta(days=1, minutes=45))

    summary = work_sessions.period_summary(days=2, now=start + timedelta(days=1, hours=1))

    assert summary["total_seconds"] == 75 * 60
    assert [day["elapsed_seconds"] for day in summary["daily"]] == [30 * 60, 45 * 60]
    assert summary["tasks"][0]["task_id"] == "task-1"
    assert summary["tasks"][0]["elapsed_seconds"] == 75 * 60
    assert summary["tasks"][0]["session_count"] == 2


def test_event_history_counts_pause_across_local_midnight(tmp_path, monkeypatch):
    monkeypatch.setattr(work_sessions.db.config, "DB_PATH", tmp_path / "test.db")
    start = datetime(2026, 8, 1, 14, 30, tzinfo=timezone.utc)  # 23:30 JST
    work_sessions.start_session("s1", "深夜作業", now=start)
    work_sessions.pause_session("s1", now=start + timedelta(minutes=45))  # 00:15 JST
    work_sessions.resume_session("s1", now=start + timedelta(minutes=75))
    work_sessions.end_session("s1", now=start + timedelta(minutes=105))

    summary = work_sessions.period_summary(days=2, now=start + timedelta(hours=2))

    assert [day["elapsed_seconds"] for day in summary["daily"]] == [30 * 60, 45 * 60]
