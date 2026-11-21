"""Tests for PETIT's self-knowledge documentation DB and search_petit_docs tool."""
from __future__ import annotations

import json
import time
from pathlib import Path

from backend import brain, brain_catalog, config, petit_docs, tools


def _write_doc(root: Path, rel_path: str, content: str) -> Path:
    target = root / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def test_split_markdown_ignores_fenced_headings() -> None:
    text = (
        "# PETIT ガイド\n\n"
        "> Status: **現行**\n\n"
        "## 音声会話\n"
        "```bash\n"
        "# これはコメントであり見出しではない\n"
        "echo hello\n"
        "```\n"
        "話しかけると音声で返答します。\n"
    )
    chunks = petit_docs._split_markdown_chunks(text, "PETIT ガイド")
    assert len(chunks) == 2
    assert chunks[0][0] == "PETIT ガイド"
    assert chunks[1][0] == "PETIT ガイド > 音声会話"
    assert "# これはコメントであり見出しではない" in chunks[1][1]


def test_sync_and_search_petit_docs_lifecycle(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    storage = tmp_path / "storage"
    repo.mkdir()
    storage.mkdir()
    monkeypatch.setattr(config, "STORAGE_DIR", storage)

    (repo / "VERSION").write_text("0.99.0\n", encoding="utf-8")
    _write_doc(
        repo,
        "Concept.md",
        "# PETIT Concept\n\n> Status: **目標**\n\n## 誰のためのものか\n自分専用のAI秘書。\n",
    )
    _write_doc(
        repo,
        "docs/life/reminders.md",
        "# リマインダー\n\n> Status: **現行**\n\n## 使い方\n予定の前にリマインダーで通知します。\n",
    )
    _write_doc(
        repo,
        "docs/voice/voice_mode.md",
        "# 音声モード\n\n> Status: **現行**\n\n## 概要\n音声で会話できます。\n",
    )
    _write_doc(
        repo,
        "docs/archive/old_note.md",
        "# 旧仕様\n\nアーカイブされた古い情報です。\n",
    )

    first = petit_docs.sync_petit_docs(base_dir=repo)
    assert first["files"] == 3
    assert first["added"] == 3
    assert first["deleted"] == 0

    second = petit_docs.sync_petit_docs(base_dir=repo)
    assert second["skipped"] == 3
    assert second["added"] == 0
    assert second["updated"] == 0

    # Short 2-char Japanese keyword should match via LIKE fallback
    voice_res = petit_docs.search_petit_docs("音声", base_dir=repo)
    assert voice_res["petit_version"] == "0.99.0"
    assert voice_res["count"] >= 1
    assert voice_res["results"][0]["doc_path"] == "docs/voice/voice_mode.md"
    assert voice_res["results"][0]["status"] == "現行"

    # 3+ char Japanese keyword
    rem_res = petit_docs.search_petit_docs("リマインダー", base_dir=repo)
    assert rem_res["count"] >= 1
    assert rem_res["results"][0]["doc_path"] == "docs/life/reminders.md"

    # Archive must be excluded
    arch_res = petit_docs.search_petit_docs("アーカイブされた古い情報", base_dir=repo)
    assert arch_res["count"] == 0

    # Category filter
    cat_res = petit_docs.search_petit_docs("秘書", category="life", base_dir=repo)
    assert cat_res["count"] == 0

    # Update a file and verify incremental re-index
    time.sleep(0.02)
    _write_doc(
        repo,
        "docs/voice/voice_mode.md",
        "# 音声モード\n\n> Status: **現行**\n\n## 概要\nウェイクワードで起動します。\n",
    )
    updated_res = petit_docs.search_petit_docs("ウェイクワード", base_dir=repo)
    assert updated_res["count"] == 1
    assert updated_res["results"][0]["doc_path"] == "docs/voice/voice_mode.md"

    # Delete a file and verify removal
    (repo / "docs/voice/voice_mode.md").unlink()
    deleted_res = petit_docs.search_petit_docs("ウェイクワード", base_dir=repo)
    assert deleted_res["count"] == 0


def test_search_petit_docs_tool_registered_and_dispatches(tmp_path: Path, monkeypatch) -> None:
    storage = tmp_path / "storage"
    storage.mkdir()
    monkeypatch.setattr(config, "STORAGE_DIR", storage)

    tools.register_builtin_tools()
    assert "search_petit_docs" in tools.registered_names()
    assert "search_petit_docs" in brain.PUBLIC_TOOLS
    assert tools.risk_for("search_petit_docs") == "safe_read"

    schema = {"function": {"name": "search_petit_docs"}}
    setup = {"connected": [], "secrets": {}}
    assert brain_catalog.available(schema, local_only=True, setup=setup) is True

    raw = tools.dispatch("search_petit_docs", {"query": "リマインダー", "limit": 3})
    payload = json.loads(raw)
    assert payload["count"] >= 1
    assert any(item["doc_path"].startswith("docs/") for item in payload["results"])
