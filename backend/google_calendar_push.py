"""Optional TimeTree -> Google Calendar push sync.

Disabled by default. Enable only with PETIT_GOOGLE_CALENDAR_SYNC_ENABLED=1.
Authentication uses a user OAuth token file created by tools/google_calendar_auth.py.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import config

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def enabled() -> bool:
    return os.getenv("PETIT_GOOGLE_CALENDAR_SYNC_ENABLED", "0") not in ("0", "false", "False")


def calendar_id() -> str:
    return os.getenv("PETIT_GOOGLE_CALENDAR_ID", "primary").strip() or "primary"


def credentials_file() -> Path:
    raw = os.getenv("PETIT_GOOGLE_CALENDAR_CREDENTIALS_FILE", "").strip().strip('"')
    return Path(raw) if raw else config.STORAGE_DIR / "google_calendar_credentials.json"


def token_file() -> Path:
    raw = os.getenv("PETIT_GOOGLE_CALENDAR_TOKEN_FILE", "").strip().strip('"')
    return Path(raw) if raw else config.STORAGE_DIR / "google_calendar_token.json"


def load_credentials(*, allow_interactive: bool = False):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:  # pragma: no cover - dependency setup issue
        raise RuntimeError("Google Calendar API ライブラリがインストールされていません") from exc

    token_path = token_file()
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")

    if creds and creds.valid:
        return creds

    if not allow_interactive:
        raise RuntimeError("Google Calendar OAuth が未設定です。tools/google_calendar_auth.py を実行してください")

    credentials_path = credentials_file()
    if not credentials_path.exists():
        raise RuntimeError(f"Google OAuth credentials が見つかりません: {credentials_path}")

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
    creds = flow.run_local_server(port=0)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _service():
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Google Calendar API ライブラリがインストールされていません") from exc
    return build("calendar", "v3", credentials=load_credentials(allow_interactive=False), cache_discovery=False)


def _event_time(value: str | None, *, is_end: bool = False) -> dict[str, str] | None:
    if not value:
        return None
    if len(value) == 10 and value[4] == "-" and value[7] == "-":
        if is_end:
            return {"date": value}
        return {"date": value}
    return {"dateTime": value}


def _description(event: dict[str, Any]) -> str:
    original = (event.get("description") or "").strip()
    metadata = ["[PETIT / TimeTree]"]
    if event.get("label_name"):
        metadata.append(f"TimeTreeラベル: {event['label_name']}")
    if event.get("label_color"):
        metadata.append(f"TimeTreeラベル色: {event['label_color']}")
    suffix = "\n".join(metadata)
    return f"{original}\n\n{suffix}" if original else suffix


def _body(event: dict[str, Any]) -> dict[str, Any]:
    uid = str(event.get("external_id") or "").strip()
    if not uid:
        raise ValueError("TimeTree event external_id is required")

    start = _event_time(event.get("start_time"))
    if not start:
        raise ValueError("TimeTree event start_time is required")

    end_value = event.get("end_time")
    if len(str(event.get("start_time") or "")) == 10 and not end_value:
        start_date = datetime.fromisoformat(str(event["start_time"])).date()
        end_value = (start_date + timedelta(days=1)).isoformat()
    end = _event_time(end_value, is_end=True) or start

    private = {
        "petit_source": "timetree",
        "petit_timetree_uid": uid,
    }
    if event.get("label_name"):
        private["timetree_label"] = str(event["label_name"])
    if event.get("label_id"):
        private["timetree_label_id"] = str(event["label_id"])
    if event.get("label_color"):
        private["timetree_label_color"] = str(event["label_color"])

    body: dict[str, Any] = {
        "summary": event["title"],
        "start": start,
        "end": end,
        "description": _description(event),
        "extendedProperties": {"private": private},
    }
    if event.get("location"):
        body["location"] = event["location"]
    return body


def sync_events(events: list[dict[str, Any]]) -> dict[str, int]:
    """Create or update Google events matched by the TimeTree UID. Never deletes."""
    if not enabled():
        return {"created": 0, "updated": 0, "skipped": len(events)}

    service = _service()
    target = calendar_id()
    created = updated = skipped = 0

    for event in events:
        uid = str(event.get("external_id") or "").strip()
        if not uid:
            skipped += 1
            continue
        matches = service.events().list(
            calendarId=target,
            privateExtendedProperty=f"petit_timetree_uid={uid}",
            maxResults=2,
            singleEvents=False,
        ).execute().get("items", [])
        body = _body(event)
        if matches:
            service.events().patch(
                calendarId=target,
                eventId=matches[0]["id"],
                body=body,
                sendUpdates="none",
            ).execute()
            updated += 1
        else:
            service.events().insert(
                calendarId=target,
                body=body,
                sendUpdates="none",
            ).execute()
            created += 1

    return {"created": created, "updated": updated, "skipped": skipped}
