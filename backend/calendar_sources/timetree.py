"""TimeTree read-only ICS adapter; credentials never enter results or logs."""
from __future__ import annotations

import os
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
    try:
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
