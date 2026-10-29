"""Install Google's official Antigravity ACP binary from the ACP Registry.

The installer uses a versioned PETIT-local directory and never edits or replaces
the separate `agy` CLI installation.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import sys
import tempfile
import urllib.request
import zipfile

REGISTRY_URL = "https://cdn.agentclientprotocol.com/registry/v1/latest/registry.json"
GOOGLE_HOSTS = {"dl.google.com"}
REGISTRY_HOSTS = {"cdn.agentclientprotocol.com"}


def platform_key() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    os_name = {"windows": "windows", "darwin": "darwin", "linux": "linux"}.get(system)
    arch = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}.get(machine)
    if not os_name or not arch:
        raise RuntimeError("unsupported_platform")
    return f"{os_name}-{arch}"


def read_url(url: str, limit: int, allowed_hosts: set[str]) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 PETIT-Antigravity-ACP-installer"})
    with urllib.request.urlopen(request, timeout=30) as response:
        from urllib.parse import urlparse
        if response.status != 200 or urlparse(response.geturl()).hostname not in allowed_hosts:
            raise RuntimeError("untrusted_download_host")
        data = response.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError("download_too_large")
    return data


def registry_entry() -> tuple[str, dict]:
    registry = json.loads(read_url(REGISTRY_URL, 8 * 1024 * 1024, REGISTRY_HOSTS))
    agent = next((item for item in registry.get("agents", []) if item.get("id") == "antigravity-acp"), None)
    if not agent or agent.get("authors") != ["Google LLC"] or agent.get("license") != "proprietary":
        raise RuntimeError("official_registry_entry_missing")
    key = platform_key()
    item = agent.get("distribution", {}).get("binary", {}).get(key)
    if not isinstance(item, dict) or not isinstance(item.get("sha256"), str):
        raise RuntimeError("platform_distribution_missing_checksum")
    from urllib.parse import urlparse
    if urlparse(item.get("archive", "")).hostname not in GOOGLE_HOSTS:
        raise RuntimeError("untrusted_archive_host")
    if not item["sha256"].lower().isalnum() or len(item["sha256"]) != 64:
        raise RuntimeError("invalid_registry_checksum")
    return str(agent["version"]), item


def install(destination: Path | None = None) -> dict:
    version, distribution = registry_entry()
    archive = read_url(distribution["archive"], 256 * 1024 * 1024, GOOGLE_HOSTS)
    digest = hashlib.sha256(archive).hexdigest()
    if digest != distribution["sha256"].lower():
        raise RuntimeError("archive_checksum_mismatch")
    default_root = Path(os.getenv("LOCALAPPDATA") or Path.home() / ".local" / "share") / "PETIT" / "antigravity-acp"
    root = (destination or default_root).expanduser().resolve()
    target = root / version
    executable = Path(distribution["cmd"].removeprefix("./"))
    if target.exists():
        candidate = target / executable
        if candidate.is_file():
            return {"installed": True, "version": version, "path": str(candidate), "sha256": digest,
                    "already_present": True, "auth": "unknown"}
        raise RuntimeError("version_target_exists_without_agent")
    root.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=".acp-install-", dir=root))
    try:
        with zipfile.ZipFile(__import__("io").BytesIO(archive)) as bundle:
            for item in bundle.infolist():
                name = PurePosixPath(item.filename)
                if name.is_absolute() or ".." in name.parts:
                    raise RuntimeError("unsafe_archive_path")
                out = temp.joinpath(*name.parts)
                if item.is_dir():
                    out.mkdir(parents=True, exist_ok=True)
                else:
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(item) as src, out.open("xb") as dst:
                        shutil.copyfileobj(src, dst)
        candidate = temp / executable
        if not candidate.is_file():
            raise RuntimeError("registry_command_not_found_in_archive")
        metadata = {"id": "antigravity-acp", "version": version, "archive_sha256": digest,
                    "registry": REGISTRY_URL, "command": distribution["cmd"], "auth": "unknown"}
        (temp / "registry-install.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        temp.replace(target)
        return {"installed": True, "version": version, "path": str(target / executable), "sha256": digest,
                "already_present": False, "auth": "unknown"}
    finally:
        if temp.exists():
            shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    try:
        print(json.dumps(install(), ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"installed": False, "error": str(exc)[:120]}, ensure_ascii=False))
        sys.exit(1)
