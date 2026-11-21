"""Core-owned PC reads, job scratch copies, and single-use host action approvals."""
from collections import deque
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import time
from uuid import uuid4

from . import antigravity_cli_brain, config, db

MAX_COPY = 32 * 1024 * 1024
PRIVATE = {
    "_private", ".ssh", ".gnupg", ".aws", ".azure", ".kube", ".config", ".codex", ".claude",
    ".gemini", ".antigravity", ".git", "credentials", "secrets", "keychains",
    "chrome", "chromium", "microsoftedge", "edge", "firefox", "bravesoftware", "opera software",
    "windowsapps", "protect", "vault", "proc", "sys", "dev",
    "system volume information", "$recycle.bin", "login data", "local state", "cookies",
    "web data", "ntuser.dat", "sam", "shadow", ".netrc", "_netrc", ".npmrc", ".pypirc",
}
PROTECTED_EXTENSIONS = {".pem", ".key", ".pfx", ".p12", ".kdbx", ".ppk"}
ACTION_SCHEMA = """
CREATE TABLE IF NOT EXISTS coding_pc_actions (
 id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES coding_jobs(id), operation TEXT NOT NULL,
 parameters TEXT NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL, result_json TEXT
)
"""

MAX_COMMAND_STDOUT = 32768
MAX_COMMAND_STDERR = 16384

# 安全な読み取り専用の PowerShell コマンドレット（初期ホワイトリスト）
DEFAULT_READONLY_PS_CMDLETS = {
    "get-winevent", "get-eventlog", "get-computerinfo", "get-ciminstance", "get-wmiobject",
    "get-hotfix", "get-service", "get-process", "get-disk", "get-volume", "get-partition",
    "get-physicaldisk", "get-netadapter", "get-netipaddress", "get-netipconfiguration",
    "get-netroute", "get-dnsclientserveraddress", "get-childitem", "get-item",
    "get-itemproperty", "get-content", "get-date", "get-timezone", "get-uptime",
    "get-scheduledtask", "get-scheduledtaskinfo", "get-appxpackage", "get-package",
    "test-connection", "test-netconnection", "resolve-dnsname",
}

# パイプの後ろで許可する純粋な整形・フィルタ用コマンドレット
_SAFE_PS_PIPE_CMDLETS = {
    "select-object", "select", "where-object", "where", "sort-object", "sort",
    "format-list", "format-table", "fl", "ft", "out-string", "measure-object",
    "group-object", "convertto-json",
}

# 破壊的・変更系の PowerShell トークン／演算子（文字列・ハッシュテーブル外の `;` はパーサ側で拒否）
_UNSAFE_PS_PATTERN = re.compile(
    r"(?:&&|\|\||>>|>|\$\(|`|\b(?:invoke-|iex|irm|iwr|start-|stop-|restart-|remove-|set-|new-|clear-|disable-|enable-|register-|unregister-|write-|out-file|tee-object|export-|import-module|add-|rename-|move-|copy-|del|erase|rmdir|rm|mv|cp)\b)",
    re.IGNORECASE,
)

# 引数不問で安全な読み取り系コマンド（ベース名小文字）
DEFAULT_READONLY_EXES = {
    "systeminfo.exe", "whoami.exe", "hostname.exe", "ver.exe", "tasklist.exe",
    "driverquery.exe", "ipconfig.exe", "getmac.exe", "quser.exe", "qwinsta.exe",
    "where.exe", "chcp.com",
}

# 第1引数（サブコマンド）が安全な読み取り系の場合のみ許可するコマンド
DEFAULT_READONLY_SUBCOMMANDS = {
    "wevtutil.exe": {"qe", "query-events", "gl", "get-log", "el", "enum-logs", "gli", "get-loginfo"},
    "powercfg.exe": {"/lastwake", "-lastwake", "/requests", "-requests", "/availablesleepstates", "/a", "-a", "/devicequery", "-devicequery", "/sleepstudy", "-sleepstudy", "/batteryreport", "-batteryreport", "/systempowerreport", "-systempowerreport"},
    "sc.exe": {"query", "queryex", "qc", "qdescription", "getdisplayname"},
    "git.exe": {"status", "log", "diff", "show", "branch", "rev-parse"},
}


def ensure_schema(connection):
    connection.executescript(ACTION_SCHEMA)
    cols = {row[1] for row in connection.execute("PRAGMA table_info(coding_pc_actions)").fetchall()}
    if "result_json" not in cols:
        connection.execute("ALTER TABLE coding_pc_actions ADD COLUMN result_json TEXT")


def _extract_ps_command(argv):
    if not argv:
        return None
    exe = Path(argv[0]).name.casefold()
    if exe not in {"powershell.exe", "pwsh.exe"}:
        return None
    i = 1
    while i < len(argv):
        arg = argv[i].casefold()
        if arg in {"-command", "-c"} and i + 1 < len(argv):
            return argv[i + 1]
        if arg in {"-encodedcommand", "-enc", "-file", "-f"}:
            return None
        i += 1
    return None


def _ps_segments_and_head(script):
    if not script or _UNSAFE_PS_PATTERN.search(script):
        return None, None
    # 文字列リテラルおよび @{...} 外のパイプで分割し、外の ';' は拒否する
    segments = []
    buf = []
    quote = None
    brace_depth = 0
    for idx, ch in enumerate(script):
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in {"'", '"'}:
            quote = ch
            buf.append(ch)
        elif ch == "{" and idx > 0 and script[idx - 1] == "@":
            brace_depth += 1
            buf.append(ch)
        elif ch == "{" and brace_depth > 0:
            brace_depth += 1
            buf.append(ch)
        elif ch == "}" and brace_depth > 0:
            brace_depth -= 1
            buf.append(ch)
        elif ch == ";" and brace_depth == 0:
            return None, None
        elif ch == "|" and brace_depth == 0:
            segments.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if quote is not None or brace_depth != 0:
        return None, None
    segments.append("".join(buf).strip())
    if not segments or not segments[0]:
        return None, None
    heads = []
    for seg in segments:
        if not seg:
            return None, None
        token = seg.split(None, 1)[0].casefold()
        if not re.fullmatch(r"[a-z0-9_.-]+", token):
            return None, None
        heads.append(token)
    return heads, heads[0]


def whitelist_signature(argv):
    if not argv:
        return None
    exe = Path(argv[0]).name.casefold()
    script = _extract_ps_command(argv)
    if script is not None:
        heads, head = _ps_segments_and_head(script)
        if heads and all(h in _SAFE_PS_PIPE_CMDLETS for h in heads[1:]):
            return f"ps:{head}"
        digest = hashlib.sha256(script.strip().encode("utf-8")).hexdigest()[:16]
        return f"ps_exact:{digest}"
    if exe in {"powershell.exe", "pwsh.exe", "cmd.exe"}:
        # Arbitrary shell invocations (-File, -EncodedCommand, /c) must match exact arguments.
        digest = hashlib.sha256(json.dumps([exe, *argv[1:]], ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
        return f"shell_exact:{exe}:{digest}"
    if exe in DEFAULT_READONLY_SUBCOMMANDS and len(argv) >= 2:
        return f"exe:{exe}:{argv[1].casefold()}"
    if exe == "netsh.exe" and len(argv) >= 3 and "show" in [a.casefold() for a in argv[1:4]]:
        return f"exe:netsh.exe:show:{argv[1].casefold()}"
    if len(argv) >= 2 and not argv[1].startswith(("/", "-")):
        return f"exe:{exe}:{argv[1].casefold()}"
    return f"exe:{exe}"


def is_whitelisted_command(argv):
    if not argv:
        return False
    exe = Path(argv[0]).name.casefold()
    script = _extract_ps_command(argv)
    if script is not None:
        heads, head = _ps_segments_and_head(script)
        if heads and all(h in _SAFE_PS_PIPE_CMDLETS for h in heads[1:]):
            if head in DEFAULT_READONLY_PS_CMDLETS:
                return True
    elif exe in DEFAULT_READONLY_EXES:
        return True
    elif exe in DEFAULT_READONLY_SUBCOMMANDS and len(argv) >= 2:
        if argv[1].casefold() in DEFAULT_READONLY_SUBCOMMANDS[exe]:
            return True
    elif exe == "netsh.exe" and "show" in [a.casefold() for a in argv[1:4]]:
        return True

    sig = whitelist_signature(argv)
    if not sig:
        return False
    from . import setup_store as settings
    user_list = settings.load().get("pc_command_whitelist") or []
    return sig in user_list


def list_whitelist():
    from . import setup_store as settings
    return {
        "default_ps_cmdlets": sorted(DEFAULT_READONLY_PS_CMDLETS),
        "default_exes": sorted(DEFAULT_READONLY_EXES),
        "default_subcommands": {k: sorted(v) for k, v in DEFAULT_READONLY_SUBCOMMANDS.items()},
        "user_whitelist": list(settings.load().get("pc_command_whitelist") or []),
    }


def add_to_whitelist(argv):
    sig = whitelist_signature(argv)
    if not sig:
        return None
    from . import setup_store as settings
    with settings._guard():
        current = list(settings.load().get("pc_command_whitelist") or [])
        if sig not in current:
            current.append(sig)
            settings.update({"pc_command_whitelist": current})
    return sig


def remove_from_whitelist(signature):
    from . import setup_store as settings
    with settings._guard():
        current = list(settings.load().get("pc_command_whitelist") or [])
        updated = [item for item in current if item != signature]
        if len(updated) != len(current):
            settings.update({"pc_command_whitelist": updated})
    return updated


def permitted_path(path):
    return permitted_parts(path.parts[1:]) and not path.is_relative_to(Path(config.STORAGE_DIR).absolute())


def permitted_parts(parts):
    for part in parts:
        normalized = part.casefold().rstrip(" .")
        if (not normalized or normalized in PRIVATE or normalized.startswith((".env", "id_rsa", "id_ed25519"))
                or Path(normalized).suffix in PROTECTED_EXTENSIONS or re.search(r"credential|auth[_-]?token|oauth", normalized)
                or "~" in part or ":" in part or normalized != part.casefold()
                or re.fullmatch(r"(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", normalized)):
            return False
    return True


def host_path(value, root=None, *, missing=False, directory=False):
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or (os.name == "nt" and path.drive.startswith("\\")):
        raise ValueError("PC上の絶対パスを指定してください。")
    if (root and not path.is_relative_to(Path(root))) or not permitted_path(path):
        raise ValueError("対象範囲外または保護されたパスです。")
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            if missing and item == path:
                continue
            raise
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("リンクを経由するパスは扱えません。")
        if item == path:
            if directory and not stat.S_ISDIR(info.st_mode):
                raise ValueError("フォルダを指定してください。")
            if not directory and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
                raise ValueError("リンクされていない通常ファイルを指定してください。")
    return path


def _search_roots(root):
    if root:
        return [host_path(root, directory=True)]
    if os.name == "nt":
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        return [Path(f"{chr(65 + i)}:/") for i in range(26) if mask & (1 << i)]
    return [Path("/")]


def _everything(query):
    if os.name != "nt":
        return None
    from . import everything_ipc
    try:
        result = everything_ipc.search(query)
        if result is not None:
            return result
    except (OSError, ValueError):
        pass
    installed = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Everything" / "es.exe"
    executable = shutil.which("es.exe") or (str(installed) if installed.is_file() else None)
    if not executable:
        return None
    # Search syntax is literal and cannot supply ES switches.
    try:
        result = subprocess.run([executable, "-n", "500", "-timeout", "1500", "-no-folders", "-search*", query],
                                stdin=subprocess.DEVNULL, capture_output=True, timeout=4,
                                creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.decode("utf-8-sig", "replace").splitlines() if result.returncode == 0 else None


def search(query, root, check):
    query = query.strip()
    if not 2 <= len(query) <= 150 or any(ord(c) < 32 for c in query):
        raise ValueError("検索するファイル名の一部を2〜150文字で指定してください。")
    indexed = _everything(query)
    result = []

    def add(path):
        if query.casefold() not in path.name.casefold():
            return
        try:
            result.append(str(host_path(str(path), root)))
        except (OSError, ValueError):
            pass

    if indexed is not None:
        for name in indexed:
            check()
            add(Path(name))
            if len(result) >= 50:
                break
        if result:
            return {"files": result, "source": "everything", "truncated": len(result) >= 50 or len(indexed) >= 500}
    pending = deque(_search_roots(root))
    deadline = time.monotonic() + 6
    scanned = 0
    while pending and len(result) < 50 and scanned < 30000 and time.monotonic() < deadline:
        check()
        parent = pending.popleft()
        try:
            with os.scandir(parent) as entries:
                for entry in entries:
                    scanned += 1
                    path = Path(entry.path)
                    if permitted_path(path):
                        if entry.is_dir(follow_symlinks=False):
                            try:
                                pending.append(host_path(str(path), root, directory=True))
                            except (OSError, ValueError):
                                pass
                        elif entry.is_file(follow_symlinks=False):
                            add(path)
                    if len(result) >= 50 or scanned >= 30000 or time.monotonic() >= deadline:
                        return {"files": result, "source": "filesystem", "truncated": True}
        except OSError:
            continue
    return {"files": result, "source": "filesystem", "truncated": bool(pending)}


def list_dir(path, root, check):
    """List direct subdirectories and files under an allowed PC directory."""
    check()
    cleaned = (path or "").strip()
    if not cleaned:
        roots = _search_roots(root)
        return {
            "path": root or "",
            "directories": [str(item) for item in roots],
            "files": [],
            "truncated": False,
        }
    target = host_path(cleaned, root, directory=True)
    directories, files = [], []
    truncated = False
    with os.scandir(target) as entries:
        for entry in entries:
            check()
            entry_path = Path(entry.path)
            if not permitted_path(entry_path):
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    host_path(str(entry_path), root, directory=True)
                    directories.append(entry.name)
                elif entry.is_file(follow_symlinks=False):
                    host_path(str(entry_path), root)
                    files.append(entry.name)
            except (OSError, ValueError):
                continue
            if len(directories) + len(files) >= 200:
                truncated = True
                break
    directories.sort(key=str.casefold)
    files.sort(key=str.casefold)
    return {"path": str(target), "directories": directories, "files": files, "truncated": truncated}


def read_bytes(path, limit):
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("ファイルがサイズ上限を超えています。")
    return data


def _stamp(path):
    if not path.exists():
        return None
    return hashlib.sha256(read_bytes(path, MAX_COPY)).hexdigest()


def _replace(path, data, *, overwrite):
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".petit-", delete=False) as stream:
        temp = Path(stream.name)
        try:
            stream.write(data)
            stream.close()
            if overwrite:
                os.chmod(temp, stat.S_IMODE(path.stat().st_mode))
                os.replace(temp, path)
            else:
                # Exclusive create even if another process writes after the approval check.
                if os.name == "nt":
                    os.rename(temp, path)
                else:
                    os.link(temp, path)
        finally:
            stream.close()
            temp.unlink(missing_ok=True)


def copy_to_scratch(source, destination):
    data = read_bytes(source, MAX_COPY)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Do not overwrite a previous copy or a file the agent has edited.
    with destination.open("xb") as stream:
        stream.write(data)
    return {"copied": True, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _decode_output(raw, limit):
    if not raw:
        return ""
    chunk = raw[:limit]
    for encoding in ("utf-8", "cp932"):
        try:
            text = chunk.decode(encoding)
            break
        except UnicodeDecodeError:
            text = None
    if text is None:
        text = chunk.decode("utf-8", errors="replace")
    if len(raw) > limit:
        text += "\n... (出力が上限に達したため省略しました)"
    return text


def propose(job, operation, args, scratch_path):
    root = job["repository"] or None
    if operation == "command":
        cwd = host_path(args["path"], root, directory=True)
        argv = args["argv"]
        if any("\0" in arg for arg in argv):
            raise ValueError("無効なコマンド引数です。")
        executable = shutil.which(argv[0])
        if not executable or (os.name == "nt" and Path(executable).suffix.lower() != ".exe"):
            raise ValueError("実行可能なコマンドが見つかりません。")
        binary = Path(executable).resolve(strict=True)
        parameters = {"path": str(cwd), "argv": [str(binary), *argv[1:]], "executable_stamp": _executable_stamp(binary)}
        if is_whitelisted_command(parameters["argv"]):
            result = _execute(job, "command", parameters)
            key = json.dumps(parameters, ensure_ascii=False, sort_keys=True)
            result_json = json.dumps(result, ensure_ascii=False)
            action_id = uuid4().hex
            with db.write_transaction() as connection:
                connection.execute(
                    "INSERT INTO coding_pc_actions(id,job_id,operation,parameters,status,created_at,result_json) VALUES(?,?,?,?,?,?,?)",
                    (action_id, job["id"], "command", key, "applied", time.time(), result_json),
                )
            return {"executed": True, "whitelisted": True, "action_id": action_id, **result}
    else:
        path = host_path(args["path"], root, missing=operation == "write")
        parameters = {"path": str(path), "sha256": _stamp(path)}
        if operation == "move":
            destination = host_path(args["destination"], root, missing=True)
            if destination.exists():
                raise ValueError("移動先には既存ファイルがあります。")
            parameters["destination"] = str(destination)
        if operation == "write":
            parameters["source"] = args["source"]
            parameters["source_sha256"] = _stamp(scratch_path(args["source"]))
            if not parameters["source_sha256"]:
                raise ValueError("作業場のファイルを指定してください。")
    with db.write_transaction() as connection:
        key = json.dumps(parameters, ensure_ascii=False, sort_keys=True)
        previous = connection.execute(
            "SELECT id FROM coding_pc_actions WHERE job_id=? AND operation=? AND parameters=? AND status='proposed'",
            (job["id"], operation, key)).fetchone()
        if previous:
            res = {"approval_required": True, "action_id": previous[0]}
            if operation == "command":
                res["whitelist_candidate"] = whitelist_signature(parameters["argv"])
            return res
        action_id = uuid4().hex
        connection.execute(
            "INSERT INTO coding_pc_actions(id,job_id,operation,parameters,status,created_at,result_json) VALUES(?,?,?,?,?,?,?)",
            (action_id, job["id"], operation, key, "proposed", time.time(), None),
        )
    res = {"approval_required": True, "action_id": action_id}
    if operation == "command":
        res["whitelist_candidate"] = whitelist_signature(parameters["argv"])
    return res


def actions(connection, job_id):
    items = []
    for row in connection.execute(
        "SELECT id,operation,parameters,status,result_json FROM coding_pc_actions WHERE job_id=? ORDER BY created_at", (job_id,)
    ):
        params = json.loads(row["parameters"])
        item = {
            "id": row["id"],
            "operation": row["operation"],
            "parameters": params,
            "status": row["status"],
        }
        if row["result_json"]:
            try:
                item["result"] = json.loads(row["result_json"])
            except ValueError:
                item["result"] = None
        if row["operation"] == "command" and isinstance(params.get("argv"), list):
            item["whitelist_candidate"] = whitelist_signature(params["argv"])
        items.append(item)
    return items


def resolve(job, action_id, approve, *, remember=False):
    from . import coding_jobs
    with db.write_transaction() as connection:
        row = connection.execute(
            "SELECT * FROM coding_pc_actions WHERE id=? AND job_id=?", (action_id, job["id"])).fetchone()
        if row is None:
            raise ValueError("承認対象が見つかりません。")
        current = connection.execute("SELECT status,cancel_requested FROM coding_jobs WHERE id=?", (job["id"],)).fetchone()
        if row["status"] != "proposed":
            return {"status": row["status"]}
        if not approve:
            status = "rejected"
        elif time.time() - row["created_at"] > 1800:
            status = "expired"
        elif current["status"] != "waiting_approval" or current["cancel_requested"]:
            raise ValueError("このジョブでは承認を受け付けていません。")
        elif connection.execute("SELECT 1 FROM coding_pc_actions WHERE job_id=? AND status='running'", (job["id"],)).fetchone():
            raise ValueError("このジョブの別の操作が実行中です。")
        else:
            status = "running"
        connection.execute("UPDATE coding_pc_actions SET status=? WHERE id=?", (status, action_id))
    params = json.loads(row["parameters"])
    added_whitelist = None
    exec_result = None
    if status == "running":
        try:
            if job["repository"]:
                coding_jobs.require_repository(job["repository"])
            exec_result = _execute(job, row["operation"], params)
            status = "applied"
            if remember and row["operation"] == "command" and isinstance(params.get("argv"), list):
                added_whitelist = add_to_whitelist(params["argv"])
        except (OSError, ValueError, subprocess.SubprocessError):
            # A timeout or failure can occur after an external effect.
            status = "unknown"
        result_json = json.dumps(exec_result, ensure_ascii=False) if exec_result is not None else None
        with db.get_connection() as connection:
            connection.execute(
                "UPDATE coding_pc_actions SET status=?, result_json=? WHERE id=?",
                (status, result_json, action_id),
            )
    should_resume = row["operation"] == "command" and status == "applied"
    with db.write_transaction() as connection:
        pending = connection.execute(
            "SELECT 1 FROM coding_pc_actions WHERE job_id=? AND status IN ('proposed','running')", (job["id"],)).fetchone()
        if not pending:
            next_status = "queued" if should_resume else "ready_for_review"
            connection.execute(
                "UPDATE coding_jobs SET status=?,updated_at=? WHERE id=? AND status='waiting_approval'",
                (next_status, db.now_iso(), job["id"]),
            )
            if should_resume:
                coding_jobs.event(job["id"], "resumed_after_approval", action_id)
    response = {"status": status, "resumed": bool(not pending and should_resume)}
    if added_whitelist:
        response["whitelisted"] = added_whitelist
    if exec_result is not None:
        response["result"] = exec_result
    return response


def preview(job, action_id):
    import difflib
    from .coding_jobs import path_for
    item = next((x for x in job.get("actions", []) if x["id"] == action_id and x["operation"] == "write"), None)
    if item is None or item["status"] != "proposed":
        raise ValueError("確認できる書き込み操作がありません。")
    params = item["parameters"]
    target = host_path(params["path"], job["repository"] or None, missing=True)
    source = path_for(job["workspace"], params["source"])
    if _stamp(target) != params["sha256"] or _stamp(source) != params["source_sha256"]:
        raise ValueError("対象または作業ファイルが変更されました。")
    try:
        before = read_bytes(target, 64000).decode("utf-8-sig") if target.exists() else ""
        after = read_bytes(source, 64000).decode("utf-8-sig")
    except (UnicodeError, ValueError):
        return {"preview": "バイナリまたは表示上限を超えるファイルです。作業ファイル: " + str(source)}
    delta = difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                 fromfile="元ファイル", tofile="書き込み後")
    return {"preview": "".join(delta)[:80000] or "テキスト差分はありません。"}


def _execute(job, operation, parameters):
    from .coding_jobs import path_for
    root = job["repository"] or None
    if operation == "command":
        from .cli_job import ProcessJob
        cwd = host_path(parameters["path"], root, directory=True)
        binary = Path(parameters["argv"][0])
        if _executable_stamp(binary) != parameters["executable_stamp"]:
            raise ValueError("承認対象の実行ファイルが変更されました。")
        process = subprocess.Popen(parameters["argv"], cwd=cwd, env=antigravity_cli_brain.environment(),
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}))
        owned = None
        try:
            owned = ProcessJob(process)
            stdout_raw, stderr_raw = process.communicate(timeout=120)
            return {
                "returncode": process.returncode,
                "stdout": _decode_output(stdout_raw, MAX_COMMAND_STDOUT),
                "stderr": _decode_output(stderr_raw, MAX_COMMAND_STDERR),
            }
        finally:
            if owned:
                owned.close()
            elif process.poll() is None:
                process.kill()
            process.wait()
    path = host_path(parameters["path"], root, missing=operation == "write")
    if _stamp(path) != parameters["sha256"]:
        raise ValueError("承認後に元ファイルが変更されました。")
    if operation == "write":
        source = path_for(job["workspace"], parameters["source"])
        data = read_bytes(source, MAX_COPY)
        if hashlib.sha256(data).hexdigest() != parameters["source_sha256"]:
            raise ValueError("承認後に作業場のファイルが変更されました。")
        _replace(path, data, overwrite=parameters["sha256"] is not None)
    elif operation == "move":
        destination = host_path(parameters["destination"], root, missing=True)
        if destination.exists():
            raise ValueError("移動先には既存ファイルがあります。")
        try:
            if os.name == "nt":
                os.rename(path, destination)
                return
            os.link(path, destination)
        except OSError as exc:
            if exc.errno != errno.EXDEV and getattr(exc, "winerror", None) != 17:
                raise
            copy_to_scratch(path, destination)
            shutil.copystat(path, destination)
        path.unlink()
    elif operation == "delete":
        path.unlink()
    else:
        raise ValueError("invalid_host_action")


def _executable_stamp(path):
    info = path.stat()
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]
