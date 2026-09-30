"""TimeTree read-only ICS adapter; credentials never enter results or logs."""
from __future__ import annotations

import os
import ssl
import subprocess
import sys
import tempfile
from pathlib import Path

from .. import config


def configured() -> bool:
    return config.timetree_configured()


def fetch_ics() -> str:
    if not configured():
        raise RuntimeError("TimeTree が設定されていません")
    with tempfile.NamedTemporaryFile(suffix=".ics", delete=False) as tmp:
        output = Path(tmp.name)
    env = os.environ.copy()
    env["TIMETREE_PASSWORD"] = config.TIMETREE_PASSWORD
    ca_path: Path | None = None
    try:
        # Requests uses a bundled CA set; include OS-managed roots for this
        # exporter process while retaining certificate and hostname validation.
        if not env.get("REQUESTS_CA_BUNDLE") and not env.get("CURL_CA_BUNDLE"):
            with tempfile.NamedTemporaryFile(mode="w", encoding="ascii", suffix=".pem", delete=False) as ca:
                ca_path = Path(ca.name)
                for certificate in ssl.create_default_context().get_ca_certs(binary_form=True):
                    ca.write(ssl.DER_cert_to_PEM_cert(certificate))
            env["REQUESTS_CA_BUNDLE"] = str(ca_path)
        done = subprocess.run(
            [sys.executable, "-m", "timetree_exporter", "-e", config.TIMETREE_EMAIL,
             "-c", config.TIMETREE_CALENDAR_CODE, "-o", str(output)],
            env=env, capture_output=True, text=True, timeout=120,
        )
        if done.returncode:
            raise RuntimeError("TimeTree の取得に失敗しました")
        return output.read_text(encoding="utf-8-sig")
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("TimeTree の取得がタイムアウトしました") from exc
    finally:
        output.unlink(missing_ok=True)
        if ca_path is not None:
            ca_path.unlink(missing_ok=True)
