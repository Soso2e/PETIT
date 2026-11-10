from datetime import datetime, timezone
import pytest
from backend import db, work_sessions
from backend.tools import work_sessions as work_tools


def test_delete_work_session_exact_id(monkeypatch):
    work_sessions.ensure_schema()
    session = work_sessions.start_session("test-delete-exact-1234", "テスト作業A")
    assert session is not None

    # toolで削除
    result = work_tools.delete_work_session(session_id="test-delete-exact-1234")
    assert result["deleted"] is True
    assert result["session_id"] == "test-delete-exact-1234"

    # DBに存在しないことを確認
    with db.get_connection() as conn:
        row = conn.execute("SELECT * FROM work_sessions WHERE session_id='test-delete-exact-1234'").fetchone()
        assert row is None
        events = conn.execute("SELECT * FROM work_session_events WHERE session_id='test-delete-exact-1234'").fetchall()
        assert len(events) == 0


def test_delete_work_session_partial_id(monkeypatch):
    work_sessions.ensure_schema()
    unique_id = "test-session-unique-abc987654321"
    work_sessions.start_session(unique_id, "テスト作業B")

    # 短縮ID "abc987654321" で削除
    result = work_tools.delete_work_session(session_id="abc987654321")
    assert result["deleted"] is True
    assert result["session_id"] == unique_id


def test_delete_work_session_by_task_name(monkeypatch):
    work_sessions.ensure_schema()
    work_sessions.start_session("test-session-bytask-999", "固有タスク名XYZ")

    # タスク名で削除
    result = work_tools.delete_work_session(task="固有タスク名XYZ")
    assert result["deleted"] is True
    assert result["session_id"] == "test-session-bytask-999"


def test_delete_non_existent():
    result = work_tools.delete_work_session(session_id="non-existent-session-id-000")
    assert result["deleted"] is False
    assert "見つからない" in result["error"]
