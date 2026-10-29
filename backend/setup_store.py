"""Host-local configuration and encrypted secrets; never exported to clients."""
from __future__ import annotations

import copy
import ctypes
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import threading
import time
from contextlib import contextmanager

from . import config

_lock = threading.RLock()
_depth = threading.local()
_sessions: dict[str, float] = {}
DEFAULTS = {"completed": False, "brain_enabled": False, "priority": ["codex", "antigravity", "deepseek"],
            "brain_transport": "mixed",
            "antigravity_cli_enabled": False, "antigravity_cli_model": "",
            "coding_roots": [],
            "paid_allowed": [], "connected": [], "calendar": "local", "google_calendar_id": "primary",
            "notion_tasks_db": "", "notion_projects_db": "", "notion_pages": [],
            "antigravity_auth": "local", "antigravity_model": "", "antigravity_url": "http://127.0.0.1:1234/v1",
            "antigravity_acp_auth_last_success_utc": None, "antigravity_acp_install_path": "",
            "antigravity_acp_last_error": None,
            "deepseek_model": "deepseek-flash", "codex_model": "", "google_redirect_uri": "",
            "sync_notifications": True}


def root() -> Path:
    target = Path(os.getenv("PETIT_SETTINGS_DIR", str(config.STORAGE_DIR / "settings")))
    try:
        if target.exists():
            os.listdir(target)
    except PermissionError:
        fallback = config.STORAGE_DIR / "app_settings"
        fallback.mkdir(mode=0o700, parents=True, exist_ok=True)
        return fallback
    return target


@contextmanager
def _guard():
    """Serialize refresh/config updates across Core and SDK worker processes."""
    with _lock:
        if getattr(_depth, "active", False):
            yield
            return
        root().mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(root() / ".lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"0")
            os.lseek(fd, 0, os.SEEK_SET)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX)
            _depth.active = True
            try:
                yield
            finally:
                _depth.active = False
                os.lseek(fd, 0, os.SEEK_SET)
                if os.name == "nt":
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _protect(data: bytes, *, decrypt=False) -> bytes:
    class Blob(ctypes.Structure):
        _fields_ = [("size", ctypes.c_ulong), ("data", ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(data)
    source, output = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), Blob()
    function = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise OSError("DPAPI failed")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        ctypes.windll.kernel32.LocalFree(output.data)


def _cipher():
    from cryptography.fernet import Fernet
    folder = root()
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    keyfile = folder / "master.key"
    if not keyfile.exists():
        key = Fernet.generate_key()
        value = _protect(key) if os.name == "nt" else key
        try:
            with keyfile.open("xb") as stream:
                os.chmod(keyfile, 0o600)
                stream.write(value)
        except FileExistsError:
            pass
    key = keyfile.read_bytes()
    return Fernet(_protect(key, decrypt=True) if os.name == "nt" else key)


def load() -> dict:
    with _guard():
        path = root() / "config.enc"
        if not path.exists():
            return {**copy.deepcopy(DEFAULTS), "secrets": {}}
        # Corruption must fail closed, never reset admin or silently discard keys.
        value = json.loads(_cipher().decrypt(path.read_bytes()))
        return {**copy.deepcopy(DEFAULTS), **value}


def save(value: dict) -> None:
    with _guard():
        data = _cipher().encrypt(json.dumps(value, ensure_ascii=False).encode())
        path = root() / "config.enc"
        temp = path.with_name("config-" + secrets.token_hex(8) + ".tmp")
        try:
            with temp.open("xb") as stream:
                os.chmod(temp, 0o600)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)


def update(values: dict, credentials: dict | None = None) -> dict:
    with _guard():
        data = load()
        data.update(values)
        for name, value in (credentials or {}).items():
            if value is None:
                data["secrets"].pop(name, None)
            else:
                data["secrets"][name] = value
        save(data)
        apply_runtime(data)
        return data


def secret(name: str, fallback=""):
    return load()["secrets"].get(name, fallback)


def apply_runtime(data: dict | None = None) -> None:
    data = data or load()
    # Until setup exists, all legacy .env contracts remain unchanged.
    if not data.get("admin"):
        return
    for field, key in (("NOTION_API_KEY", "notion_key"), ("TIMETREE_EMAIL", "timetree_email"),
                       ("TIMETREE_PASSWORD", "timetree_password"), ("TIMETREE_CALENDAR_CODE", "timetree_calendar")):
        if key in data["secrets"]:
            setattr(config, field, data["secrets"][key] or "")
    for field, key in (("NOTION_TASKS_DB_ID", "notion_tasks_db"), ("NOTION_PROJECTS_DB_ID", "notion_projects_db")):
        setattr(config, field, data[key])


def initialized() -> bool:
    return bool(load().get("admin"))


def set_password(password: str) -> None:
    if len(password) < 12 or len(password) > 256:
        raise ValueError("管理者パスワードは12〜256文字で指定してください。")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    data = load()
    if not data.get("admin"):
        legacy = {"notion_key": config.NOTION_API_KEY, "timetree_email": config.TIMETREE_EMAIL,
                  "timetree_password": config.TIMETREE_PASSWORD, "timetree_calendar": config.TIMETREE_CALENDAR_CODE}
        data["secrets"].update({k: v for k, v in legacy.items() if v and k not in data["secrets"]})
        data["notion_tasks_db"] = config.NOTION_TASKS_DB_ID
        data["notion_projects_db"] = config.NOTION_PROJECTS_DB_ID
    data["admin"] = {"salt": salt.hex(), "hash": digest.hex()}
    save(data)
    apply_runtime(data)


SESSION_TTL_SECONDS = 365 * 24 * 3600


def authenticate(password: str) -> str | None:
    admin = load().get("admin")
    if not admin or len(password) > 256:
        return None
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(admin["salt"]), n=16384, r=8, p=1)
    if not hmac.compare_digest(digest.hex(), admin["hash"]):
        return None
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = time.time()
    expires_at = now + SESSION_TTL_SECONDS
    from . import db
    try:
        with db.get_connection() as conn:
            conn.execute("DELETE FROM admin_sessions WHERE expires_at <= ?", (now,))
            conn.execute("INSERT OR REPLACE INTO admin_sessions (token_hash, expires_at, created_at) VALUES (?, ?, ?)",
                         (token_hash, expires_at, db.now_iso()))
    except Exception:
        # Never issue a session token that was not durably persisted.
        return None
    with _lock:
        _sessions[token_hash] = expires_at
    return token


def valid_session(token: str) -> bool:
    if not token or len(token) > 256:
        return False
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = time.time()
    # DB is authoritative across processes; a RAM cache must never keep a revoked
    # one-year admin token valid on another worker.
    from . import db
    try:
        with db.get_connection() as conn:
            row = conn.execute("SELECT expires_at FROM admin_sessions WHERE token_hash=?", (token_hash,)).fetchone()
            if row and row["expires_at"] > now:
                with _lock:
                    _sessions[token_hash] = row["expires_at"]
                return True
            elif row:
                conn.execute("DELETE FROM admin_sessions WHERE token_hash=?", (token_hash,))
    except Exception:
        pass
    return False


def logout(token: str) -> None:
    if not token:
        return
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    from . import db
    # Revocation must complete durably before the logout endpoint reports success.
    with db.get_connection() as conn:
        conn.execute("DELETE FROM admin_sessions WHERE token_hash=?", (token_hash,))
    with _lock:
        _sessions.pop(token_hash, None)


def public() -> dict:
    data = load()
    return {**{key: data[key] for key in DEFAULTS},
            "credentials": {key: bool(value) for key, value in data["secrets"].items()
                            if key not in {"google_tokens", "oauth_pending"}},
            "google_scopes": data["secrets"].get("google_tokens", {}).get("scopes", []),
            "initialized": bool(data.get("admin"))}
