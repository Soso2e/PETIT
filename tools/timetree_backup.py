"""
TimeTree iCal バックアップスクリプト

TimeTree の iCal URL からスケジュールを取得し、
SQLite と Markdown に保存する。

使い方:
    python tools/timetree_backup.py

環境変数:
    TIMETREE_ICAL_URL  - TimeTree の iCal URL (webcal:// または https://)

iCal URL の取得方法:
    TimeTree → カレンダー設定 → 同期設定 → iCal リンクをコピー
"""

import os
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.request import urlopen
from urllib.error import URLError

try:
    from icalendar import Calendar
except ImportError:
    print("ERROR: icalendar パッケージが必要です。")
    print("       pip install icalendar")
    sys.exit(1)

# --- パス設定 ---
ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "storage" / "app.db"
LOGS_DIR = ROOT / "storage" / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)


def get_ical_url() -> str:
    url = os.environ.get("TIMETREE_ICAL_URL", "")
    if not url:
        raise ValueError(
            "環境変数 TIMETREE_ICAL_URL が設定されていません。\n"
            "TimeTree → カレンダー設定 → 同期設定 → iCal リンクを設定してください。\n"
            "例: export TIMETREE_ICAL_URL='webcal://timetreeapp.com/...'"
        )
    # webcal:// → https:// に変換
    return url.replace("webcal://", "https://")


def fetch_ical(url: str) -> Calendar:
    try:
        with urlopen(url, timeout=30) as resp:
            data = resp.read()
    except URLError as e:
        raise RuntimeError(f"iCal の取得に失敗しました: {e}") from e
    return Calendar.from_ical(data)


def parse_dt(dt_val) -> datetime | None:
    """icalendar の日時/日付を UTC aware datetime に変換する。"""
    if dt_val is None:
        return None
    if isinstance(dt_val, datetime):
        if dt_val.tzinfo is None:
            return dt_val.replace(tzinfo=timezone.utc)
        return dt_val.astimezone(timezone.utc)
    if isinstance(dt_val, date):
        return datetime(dt_val.year, dt_val.month, dt_val.day, tzinfo=timezone.utc)
    return None


def extract_events(cal: Calendar) -> list[dict]:
    events = []
    for component in cal.walk():
        if component.name != "VEVENT":
            continue

        uid = str(component.get("UID", ""))
        title = str(component.get("SUMMARY", "（タイトルなし）"))
        location = str(component.get("LOCATION", "") or "")
        description = str(component.get("DESCRIPTION", "") or "")

        start = parse_dt(component.get("DTSTART").dt if component.get("DTSTART") else None)
        end = parse_dt(component.get("DTEND").dt if component.get("DTEND") else None)
        updated = parse_dt(
            component.get("LAST-MODIFIED").dt if component.get("LAST-MODIFIED") else None
        )

        if start is None:
            continue

        events.append(
            {
                "external_id": uid,
                "source": "timetree",
                "title": title,
                "start_time": start.isoformat(),
                "end_time": end.isoformat() if end else None,
                "location": location,
                "description": description,
                "updated_at": (updated or datetime.now(timezone.utc)).isoformat(),
            }
        )

    return sorted(events, key=lambda e: e["start_time"])


def save_to_sqlite(events: list[dict]) -> int:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        """
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
        """
    )
    upserted = 0
    for ev in events:
        cur.execute(
            """
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
            """,
            ev,
        )
        upserted += 1
    con.commit()
    con.close()
    return upserted


def save_to_markdown(events: list[dict], target_date: date) -> Path:
    """対象日（デフォルト: 今日 ± 7日）のイベントを日次ログに追記する。"""
    log_path = LOGS_DIR / f"{target_date.isoformat()}.md"

    # 対象日のイベントだけ抽出
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

    # 既存ファイルに同じセクションがあれば上書き、なければ追記
    if log_path.exists():
        existing = log_path.read_text(encoding="utf-8")
        header = f"## TimeTree スケジュール ({target_date.isoformat()})"
        if header in existing:
            # セクションを置換
            import re
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

    url = get_ical_url()
    print(f"iCal URL: {url[:40]}...")

    cal = fetch_ical(url)
    events = extract_events(cal)
    print(f"取得したイベント数: {len(events)}")

    saved = save_to_sqlite(events)
    print(f"SQLite に保存: {saved} 件 ({DB_PATH})")

    # 今日 ± 7日分のMarkdownを更新
    today = date.today()
    for delta in range(-7, 8):
        target = today + timedelta(days=delta)
        path = save_to_markdown(events, target)
        day_events_count = sum(
            1 for ev in events
            if ev["start_time"].startswith(target.isoformat())
        )
        if day_events_count > 0:
            print(f"Markdown 更新: {path.name} ({day_events_count} 件)")

    print("完了")


if __name__ == "__main__":
    main()
