import os
from pathlib import Path
import pytest
from backend import setup_store
from backend.tools import coding as coding_tools


def test_add_coding_repository(tmp_path, monkeypatch):
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
