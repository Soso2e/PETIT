import struct

from backend import development_pc, everything_ipc


def test_everything_ipc_reply_decodes_unicode_and_rejects_bad_offsets():
    filename = "C:\\作業\\予定.md"
    encoded = filename.encode("utf-16-le")
    data = struct.pack("<8I", 1, 1, 0, everything_ipc.FULL_PATH, 1, 0, 28, len(encoded) // 2) + encoded + b"\0\0"
    assert everything_ipc.decode_paths(data) == [filename]
    assert everything_ipc.decode_paths(data[:-1]) is None
    invalid = data[:24] + struct.pack("<I", 0) + data[28:]
    assert everything_ipc.decode_paths(invalid) is None


def test_unindexed_drives_are_searched_and_secrets_excluded(tmp_path, monkeypatch):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    good = second / "example-plan.txt"
    good.write_text("fixture", encoding="utf-8")
    (first / ".env.example-plan").write_text("test", encoding="utf-8")
    (second / "example-plan.key").write_text("test", encoding="utf-8")
    monkeypatch.setattr(development_pc, "_everything", lambda query: None)
    monkeypatch.setattr(development_pc, "_search_roots", lambda root: [first, second])
    found = development_pc.search("example-plan", None, lambda: None)
    assert found == {"files": [str(good)], "source": "filesystem", "truncated": False}
