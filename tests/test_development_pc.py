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


def test_list_dir_lists_entries_and_excludes_protected_paths(tmp_path):
    (tmp_path / "Server").mkdir()
    (tmp_path / ".git").mkdir()
    (tmp_path / ".env").write_text("SECRET=1", encoding="utf-8")
    (tmp_path / "readme.txt").write_text("ok", encoding="utf-8")
    listed = development_pc.list_dir(str(tmp_path), None, lambda: None)
    assert listed["directories"] == ["Server"]
    assert listed["files"] == ["readme.txt"]
    assert listed["truncated"] is False


def test_list_dir_empty_path_returns_roots(tmp_path, monkeypatch):
    monkeypatch.setattr(development_pc, "_search_roots", lambda root: [tmp_path])
    listed = development_pc.list_dir("", None, lambda: None)
    assert listed["directories"] == [str(tmp_path)]
    assert listed["files"] == []


def test_readonly_command_whitelist_allows_safe_and_blocks_unsafe():
    assert development_pc.is_whitelisted_command([
        "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
        "-NoProfile", "-Command",
        "Get-WinEvent -FilterHashtable @{LogName='System'; Id=41,1074} -MaxEvents 10 | Select-Object TimeCreated, Id | Format-List",
    ])
    assert not development_pc.is_whitelisted_command([
        "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
        "-NoProfile", "-Command",
        "Get-WinEvent -MaxEvents 1; Remove-Item C:\\temp\\x.txt",
    ])
    assert not development_pc.is_whitelisted_command([
        "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
        "-NoProfile", "-Command",
        "Get-Process | Out-File C:\\temp\\p.txt",
    ])
    assert development_pc.is_whitelisted_command(["C:\\Windows\\System32\\systeminfo.exe"])
    assert development_pc.is_whitelisted_command(["C:\\Windows\\System32\\wevtutil.exe", "qe", "System", "/c:5"])
    assert not development_pc.is_whitelisted_command(["C:\\Windows\\System32\\wevtutil.exe", "cl", "System"])
    assert development_pc.is_whitelisted_command(["C:\\Windows\\System32\\powercfg.exe", "/lastwake"])
    assert not development_pc.is_whitelisted_command(["C:\\Windows\\System32\\powercfg.exe", "/hibernate", "off"])

    sig_cmd_dir = development_pc.whitelist_signature(["C:\\Windows\\System32\\cmd.exe", "/c", "dir"])
    sig_cmd_del = development_pc.whitelist_signature(["C:\\Windows\\System32\\cmd.exe", "/c", "del", "x.txt"])
    assert sig_cmd_dir.startswith("shell_exact:cmd.exe:")
    assert sig_cmd_dir != sig_cmd_del

    sig_ps_file = development_pc.whitelist_signature(["C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe", "-File", "a.ps1"])
    sig_ps_enc = development_pc.whitelist_signature(["C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe", "-EncodedCommand", "AAAA"])
    assert sig_ps_file.startswith("shell_exact:powershell.exe:")
    assert sig_ps_file != sig_ps_enc
