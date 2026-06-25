"""
TimeTree 毎日バックアップスクリプト

timetree-exporter CLI を使って TimeTree のスケジュールを取得し、
SQLite と Markdown に保存する。

使い方:
    python tools/timetree_backup.py

必要な環境変数:
    TIMETREE_EMAIL          - TimeTree アカウントのメールアドレス
    TIMETREE_PASSWORD       - TimeTree アカウントのパスワード
    TIMETREE_CALENDAR_CODE  - エクスポートするカレンダーのコード

カレンダーコードの確認方法:
    timetree-exporter -e your@email.com
    （ログイン後にカレンダー一覧が表示される）
"""

import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    from icalendar import Calendar
except ImportError:
    print("ERROR: icalendar パッケージが必要です。")
    print("       pip install icalendar timetree-exporter")
    sys.exit(1)

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "storage" / "app.db"
LOGS_DIR = ROOT / "storage" / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)


def get_env() -> tuple[str, str, str]:
    email = os.environ.get("TIMETREE_EMAIL", "")
    password = os.environ.get("TIMETREE_PASSWORD", "")
    calendar_code = os.environ.get("TIMETREE_CALENDAR_CODE", "")

    missing = [k for k, v in {
        "TIMETREE_EMAIL": email,
        "TIMETREE_PASSWORD": password,
        "TIMETREE_CALENDAR_CODE": calendar_code,
    }.items() if not v]

    if missing:
        raise ValueError(
            f"環境変数が設定されていません: {', '.join(missing)}\n"
            "カレンダーコードの確認: timetree-exporter -e your@email.com"
        )
    return email, password, calendar_code


def export_ical(email: str, password: str, calendar_code: str) -> bytes:
    """timetree-exporter を呼び出して .ics データを返す。"""
    with tempfile.NamedTemporaryFile(suffix=".ics", delete=False) as f:
        tmp_path = f.name

    env = os.environ.copy()
    env["TIMETREE_PASSWORD"] = password

    try:
        result = subprocess.run(
            [
                sys.executable, "-m", "timetree_exporter",
                "-e", email,
                "-c", calendar_code,
                "-o", tmp_path,
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"timetree-exporter が失敗しました (code {result.returncode}):\n"
                f"{result.stderr.strip()}"
            )
        return Path(tmp_path).read_bytes()
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def parse_dt(dt_val) -> datetime | None:
    if dt_val is None:
        return None
    if isinstance(dt_val, datetime):
        if dt_val.tzinfo is None:
            return dt_val.replace(tzinfo=timezone.utc)
        return dt_val.astimezone(timezone.utc)
    if isinstance(dt_val, date):
        return datetime(dt_val.year, dt_val.month, dt_val.day, tzinfo=timezone.utc)
    return None


def extract_events(ical_bytes: bytes) -> list[dict]:
    cal = Calendar.from_ical(ical_bytes)
    events = []
    for component in cal.walk():
        if component.name != "VEVENT":
            continue

        start = parse_dt(component.get("DTSTART").dt if component.get("DTSTART") else None)
        if start is None:
            continue

        end = parse_dt(component.get("DTEND").dt if component.get("DTEND") else None)
        updated = parse_dt(
            component.get("LAST-MODIFIED").dt if component.get("LAST-MODIFIED") else None
        )

        events.append({
            "external_id": str(component.get("UID", "")),
            "source": "timetree",
            "title": str(component.get("SUMMARY", "（タイトルなし）")),
            "start_time": start.isoformat(),
            "end_time": end.isoformat() if end else None,
            "location": str(component.get("LOCATION", "") or ""),
            "description": str(component.get("DESCRIPTION", "") or ""),
            "updated_at": (updated or datetime.now(timezone.utc)).isoformat(),
        })

    return sorted(events, key=lambda e: e["start_time"])


def save_to_sqlite(events: list[dict]) -> int:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS calendar_events_cache (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            source      TEXT,
            title       TEXT,
            start_time  TEXT,
            end_time    TEXT,
            location    TEXT,
            description TEXT,
            external_id TEXT UNIQUE,
            updated_at  TEXT
        )
    """)
    for ev in events:
        cur.execute("""
            INSERT INTO calendar_events_cache
                (source, title, start_time, end_time, location, description, external_id, updated_at)
            VALUES
                (:source, :title, :start_time, :end_time, :location, :description, :external_id, :updated_at)
            ON CONFLICT(external_id) DO UPDATE SET
                title       = excluded.title,
                start_time  = excluded.start_time,
                end_time    = excluded.end_time,
                location    = excluded.location,
                description = excluded.description,
                updated_at  = excluded.updated_at
        """, ev)
    con.commit()
    con.close()
    return len(events)


def save_to_markdown(events: list[dict], target_date: date) -> Path:
    import re
    log_path = LOGS_DIR / f"{target_date.isoformat()}.md"

    day_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)
    day_events = [
        ev for ev in events
        if day_start <= datetime.fromisoformat(ev["start_time"]) < day_end
    ]

    lines = [f"## TimeTree スケジュール ({target_date.isoformat()})\n"]
    if day_events:
        for ev in day_events:
            start_dt = datetime.fromisoformat(ev["start_time"]).astimezone()
            end_dt = datetime.fromisoformat(ev["end_time"]).astimezone() if ev["end_time"] else None
            time_str = start_dt.strftime("%H:%M")
            if end_dt:
                time_str += f"–{end_dt.strftime('%H:%M')}"
            loc = f" @ {ev['location']}" if ev["location"] else ""
            lines.append(f"- {time_str}  {ev['title']}{loc}")
            if ev["description"]:
                for desc_line in ev["description"].splitlines():
                    if desc_line.strip():
                        lines.append(f"  > {desc_line.strip()}")
    else:
        lines.append("- （予定なし）")

    lines.append("")
    block = "\n".join(lines)

    if log_path.exists():
        existing = log_path.read_text(encoding="utf-8")
        header = f"## TimeTree スケジュール ({target_date.isoformat()})"
        if header in existing:
            pattern = rf"(## TimeTree スケジュール \({re.escape(target_date.isoformat())}\).*?)(?=\n## |\Z)"
            existing = re.sub(pattern, block.rstrip(), existing, flags=re.DOTALL)
            log_path.write_text(existing, encoding="utf-8")
        else:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(block)
    else:
        log_path.write_text(f"# {target_date.isoformat()}\n\n" + block, encoding="utf-8")

    return log_path


def main() -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] TimeTree バックアップ開始")

    email, password, calendar_code = get_env()
    print(f"アカウント: {email} / カレンダーコード: {calendar_code}")

    print("timetree-exporter を実行中...")
    ical_bytes = export_ical(email, password, calendar_code)

    events = extract_events(ical_bytes)
    print(f"取得したイベント数: {len(events)}")

    saved = save_to_sqlite(events)
    print(f"SQLite に保存: {saved} 件 ({DB_PATH})")

    today = date.today()
    for delta in range(-7, 8):
        target = today + timedelta(days=delta)
        path = save_to_markdown(events, target)
        day_count = sum(1 for ev in events if ev["start_time"].startswith(target.isoformat()))
        if day_count > 0:
            print(f"Markdown 更新: {path.name} ({day_count} 件)")

    print("完了")


if __name__ == "__main__":
    main()
