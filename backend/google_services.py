"""Shared Google web OAuth with PKCE and read-only Calendar/Gmail adapters."""
from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
from urllib.parse import urlencode, quote

import httpx
from . import setup_store as settings

SCOPES = {"google_calendar": "https://www.googleapis.com/auth/calendar.readonly",
          "gmail": "https://www.googleapis.com/auth/gmail.readonly"}
_lock = threading.RLock()


class ServiceError(RuntimeError):
    def __init__(self, code: str, status: int = 0):
        self.code, self.status = code, status
        super().__init__(code)


def _json(response) -> dict:
    if response.status_code >= 400:
        raise ServiceError("authentication_expired" if response.status_code in (401, 403) else
                           "rate_limited" if response.status_code == 429 else "service_error", response.status_code)
    return response.json()


def authorize(service: str, session: str) -> dict:
    if service not in SCOPES:
        raise ValueError("unknown_google_service")
    data = settings.load()
    client_id = data["secrets"].get("google_client_id")
    redirect = data["google_redirect_uri"]
    if not client_id or not redirect:
        raise ValueError("Google OAuth Client IDと登録済みRedirect URIを設定してください。")
    verifier = secrets.token_urlsafe(48)
    state = secrets.token_urlsafe(32)
    requested = sorted(set(data["secrets"].get("google_tokens", {}).get("scopes", [])) | {SCOPES[service]})
    pending = {"state_hash": hashlib.sha256(state.encode()).hexdigest(), "verifier": verifier,
               "session_hash": hashlib.sha256(session.encode()).hexdigest(), "service": service,
               "scopes": requested, "expires": time.time() + 600, "redirect": redirect}
    settings.update({}, {"oauth_pending": pending})
    query = {"client_id": client_id, "redirect_uri": redirect, "response_type": "code", "scope": " ".join(requested),
             "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true", "state": state,
             "code_challenge_method": "S256", "code_challenge": base64.urlsafe_b64encode(
                 hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()}
    return {"url": "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(query)}


def callback(state: str, code: str, session: str) -> str:
    with _lock:
        data = settings.load()
        pending = data["secrets"].get("oauth_pending", {})
        if (pending.get("expires", 0) < time.time() or not secrets.compare_digest(
                pending.get("state_hash", ""), hashlib.sha256(state.encode()).hexdigest()) or
                not secrets.compare_digest(pending.get("session_hash", ""), hashlib.sha256(session.encode()).hexdigest())
                or not settings.valid_session(session)):
            raise ValueError("OAuth state/session expired")
        settings.update({}, {"oauth_pending": None})  # one use, including failed exchanges
        fields = {"grant_type": "authorization_code", "code": code, "code_verifier": pending["verifier"],
                  "client_id": data["secrets"]["google_client_id"], "redirect_uri": pending["redirect"]}
        if data["secrets"].get("google_client_secret"):
            fields["client_secret"] = data["secrets"]["google_client_secret"]
        tokens = _json(httpx.post("https://oauth2.googleapis.com/token", data=fields, timeout=20))
        scopes = tokens.get("scope", "").split()
        if SCOPES[pending["service"]] not in scopes:
            raise ValueError("必要な読み取り権限が許可されていません。")
        previous = data["secrets"].get("google_tokens", {})
        saved = {"access_token": tokens["access_token"], "refresh_token": tokens.get("refresh_token", previous.get("refresh_token")),
                 "expires": time.time() + int(tokens.get("expires_in", 3600)) - 60, "scopes": scopes}
        settings.update({"connected": sorted(set(data["connected"]) | {pending["service"]})}, {"google_tokens": saved})
        return pending["service"]


def access_token(service: str) -> str:
    with _lock:
        data = settings.load()
        tokens = data["secrets"].get("google_tokens", {})
        if service not in data["connected"] or SCOPES[service] not in tokens.get("scopes", []):
            raise ServiceError("not_connected")
        if tokens.get("expires", 0) > time.time():
            return tokens["access_token"]
        if not tokens.get("refresh_token"):
            raise ServiceError("authentication_expired")
        fields = {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
                  "client_id": data["secrets"].get("google_client_id", "")}
        if data["secrets"].get("google_client_secret"):
            fields["client_secret"] = data["secrets"]["google_client_secret"]
        response = _json(httpx.post("https://oauth2.googleapis.com/token", data=fields, timeout=20))
        with settings._guard():
            live = settings.load()
            current = live["secrets"].get("google_tokens", {})
            if service not in live["connected"] or live["secrets"].get("google_client_id") != data["secrets"].get("google_client_id"):
                raise ServiceError("not_connected")
            if current.get("expires", 0) > time.time():
                return current["access_token"]
            if not current or current.get("refresh_token") != tokens.get("refresh_token"):
                raise ServiceError("authentication_changed")
            current.update(access_token=response["access_token"], expires=time.time() + int(response.get("expires_in", 3600)) - 60)
            settings.update({}, {"google_tokens": current})
            return current["access_token"]


def get(service: str, path: str, params: dict | None = None) -> dict:
    base = "https://www.googleapis.com/calendar/v3/" if service == "google_calendar" else "https://gmail.googleapis.com/gmail/v1/users/me/"
    for attempt in range(2):
        response = httpx.get(base + path, params=params, headers={"Authorization": "Bearer " + access_token(service)}, timeout=25)
        if response.status_code != 401 or attempt:
            return _json(response)
        with _lock:
            tokens = settings.secret("google_tokens", {})
            tokens["expires"] = 0
            settings.update({}, {"google_tokens": tokens})
    raise ServiceError("authentication_expired")


def calendars() -> list[dict]:
    items, page = [], None
    for _ in range(100):
        data = get("google_calendar", "users/me/calendarList", {"maxResults": 250, **({"pageToken": page} if page else {})})
        items.extend({"id": x["id"], "title": x.get("summary", x["id"])} for x in data.get("items", []))
        page = data.get("nextPageToken")
        if not page:
            return items
    raise ServiceError("pagination_limit")


def calendar_changes(calendar_id: str, sync_token: str | None) -> tuple[list[dict], str, bool]:
    path = "calendars/" + quote(calendar_id, safe="") + "/events"
    reset = not bool(sync_token)
    for retry in range(2):
        items, page = [], None
        try:
            for _ in range(1000):
                params = {"maxResults": 2500, "singleEvents": "true", "showDeleted": "true"}
                if sync_token:
                    params["syncToken"] = sync_token
                if page:
                    params["pageToken"] = page
                data = get("google_calendar", path, params)
                items.extend(data.get("items", []))
                page = data.get("nextPageToken")
                if not page:
                    if not data.get("nextSyncToken"):
                        raise ServiceError("missing_sync_token")
                    return items, data["nextSyncToken"], reset
            raise ServiceError("pagination_limit")
        except ServiceError as exc:
            if exc.status != 410 or retry:
                raise
            sync_token, reset = None, True  # fetch first; never erase the good cache
    raise ServiceError("sync_failed")


def gmail_search(query: str = "", limit: int = 10, page_token: str = "") -> dict:
    data = get("gmail", "messages", {"q": query[:1000], "maxResults": max(1, min(limit, 20)),
                                     **({"pageToken": page_token} if page_token else {})})
    result = []
    for item in data.get("messages", []):
        mail = get("gmail", "messages/" + quote(item["id"], safe=""), {"format": "metadata"})
        headers = {x["name"].lower(): x["value"] for x in mail.get("payload", {}).get("headers", [])}
        result.append({"id": item["id"], "subject": headers.get("subject", ""), "from": headers.get("from", ""),
                       "date": headers.get("date", ""), "snippet": mail.get("snippet", "")})
    return {"messages": result, "next_page_token": data.get("nextPageToken"), "read_only": True}


def gmail_message(message_id: str) -> dict:
    if not message_id or len(message_id) > 200:
        raise ValueError("invalid_message_id")
    mail = get("gmail", "messages/" + quote(message_id, safe=""), {"format": "full"})
    parts = []
    def walk(part, depth=0):
        if depth > 12 or len(parts) >= 20:
            return
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            raw = part["body"]["data"][:48000]
            parts.append(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", errors="replace"))
        for child in part.get("parts", [])[:50]:
            walk(child, depth + 1)
    walk(mail.get("payload", {}))
    return {"id": mail["id"], "snippet": mail.get("snippet", ""), "body": "\n".join(parts)[:16000],
            "body_available": bool(parts), "read_only": True}


def disconnect(service: str) -> None:
    with _lock:
        data = settings.load()
        connected = [x for x in data["connected"] if x != service]
        # Shared grant remains while either service is connected; local detachment always takes effect.
        if not ({"gmail", "google_calendar"} & set(connected)):
            tokens = data["secrets"].get("google_tokens", {})
            token = tokens.get("refresh_token") or tokens.get("access_token")
            try:
                if token:
                    _json(httpx.post("https://oauth2.googleapis.com/revoke", data={"token": token}, timeout=15))
            finally:
                settings.update({"connected": connected}, {"google_tokens": None, "oauth_pending": None})
        else:
            settings.update({"connected": connected}, {"oauth_pending": None})
