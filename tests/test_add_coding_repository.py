import os
from pathlib import Path
import pytest
from backend import setup_store
from backend.tools import coding as coding_tools


def test_add_coding_repository(tmp_path, monkeypatch):
    monkeypatch.setenv("PETIT_SETTINGS_DIR", str(tmp_path / "settings"))
    # 一時リポジトリ作成
    repo_dir = tmp_path / "my_project"
    repo_dir.mkdir()
    (repo_dir / ".git").mkdir()

    abs_path = str(repo_dir.resolve())

    # ツール実行
    res = coding_tools.add_coding_repository(abs_path)
    assert res["registered"] is True
    assert res["already_registered"] is False
    assert os.path.normcase(res["path"]) == os.path.normcase(abs_path)

    # 再度実行したら already_registered == True
    res2 = coding_tools.add_coding_repository(abs_path)
    assert res2["registered"] is True
    assert res2["already_registered"] is True

    # 相対パスはエラー
    with pytest.raises(ValueError, match="絶対パス"):
        coding_tools.add_coding_repository("relative/path")


def test_add_coding_repository_is_public_and_in_catalog(tmp_path, monkeypatch):
    from backend import brain, request_context
    from backend.brain_catalog import Catalog

    monkeypatch.setenv("PETIT_SETTINGS_DIR", str(tmp_path / "settings"))
    assert "add_coding_repository" in brain.PUBLIC_TOOLS
    assert "add_coding_repository" in brain.LOCAL_WRITES
    assert "add_coding_repository" in {item["function"]["name"] for item in brain.schemas()}

    with request_context.bind(request_id=None, session_id=None, is_admin=True):
        assert "add_coding_repository" in {item["function"]["name"] for item in Catalog().full()}
    with request_context.bind(request_id=None, session_id=None, is_admin=False):
        assert Catalog().full() == []
