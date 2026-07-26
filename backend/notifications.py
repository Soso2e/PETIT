"""Web Push notification foundation with a provider boundary for future APNs.

The module owns notification subscriptions, per-category preferences, delivery
history, and the Web Push provider. Notification generation can call
``dispatch_notification`` without knowing whether Web Push or a future APNs
provider performs the delivery.
"""
from __future__ import annotations

import importlib.util
import json
import os
from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import config, db

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

CATEGORY_LABELS: dict[str, str] = {
    "work_session": "作業セッションの声かけ",
    "schedule_reminder": "予定前リマインド",
    "high_task": "Highタスクのリマインド",
    "morning_briefing": "朝ブリーフィング",
    "github_ci_failure": "GitHub CI失敗",
}
DEFAULT_PREFERENCES = {category: False for category in CATEGORY_LABELS}

_NOTIFICATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    provider         TEXT NOT NULL DEFAULT 'web_push',
    endpoint         TEXT NOT NULL UNIQUE,
    p256dh           TEXT NOT NULL,
    auth             TEXT NOT NULL,
    content_encoding TEXT,
    user_agent       TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    disabled_at      TEXT
);

CREATE TABLE IF NOT EXISTS notification_preferences (
    owner_id    TEXT NOT NULL,
    category    TEXT NOT NULL,
    enabled     INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (owner_id, category)
);

CREATE TABLE IF NOT EXISTS notification_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    category     TEXT NOT NULL,
    title        TEXT NOT NULL,
    body         TEXT NOT NULL,
    target_url   TEXT NOT NULL DEFAULT '/',
    payload_json TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notification_deliveries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id        INTEGER NOT NULL,
    provider        TEXT NOT NULL,
    subscription_id INTEGER,
    status          TEXT NOT NULL,
    error           TEXT,
    created_at      TEXT NOT NULL,
    sent_at         TEXT,
    FOREIGN KEY(event_id) REFERENCES notification_events(id) ON DELETE CASCADE,
    FOREIGN KEY(subscription_id) REFERENCES push_subscriptions(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_push_subscriptions_active
ON push_subscriptions(provider, disabled_at, id);

CREATE INDEX IF NOT EXISTS idx_notification_events_created
ON notification_events(created_at, id);

CREATE INDEX IF NOT EXISTS idx_notification_deliveries_event
ON notification_deliveries(event_id, id);
"""


class NotificationProvider(Protocol):
    """Provider boundary shared by Web Push and a future APNs provider."""

    name: str

    def send(self, subscription: dict[str, Any], payload: dict[str, Any]) -> None:
        """Deliver one notification or raise ``NotificationDeliveryError``."""


@dataclass(slots=True)
class NotificationDeliveryError(RuntimeError):
    message: str
    permanent: bool = False

    def __str__(self) -> str:
        return self.message


class WebPushProvider:
    name = "web_push"

    def __init__(self, *, private_key: str, subject: str, ttl_seconds: int = 300) -> None:
        self.private_key = private_key
        self.subject = subject
        self.ttl_seconds = ttl_seconds

    def send(self, subscription: dict[str, Any], payload: dict[str, Any]) -> None:
        try:
            from pywebpush import WebPushException, webpush
        except ImportError as exc:  # pragma: no cover - exercised by status checks
            raise NotificationDeliveryError(
                "pywebpush is not installed. Run pip install -r requirements.txt.",
            ) from exc

        try:
            webpush(
                subscription_info={
                    "endpoint": subscription["endpoint"],
                    "keys": {
                        "p256dh": subscription["p256dh"],
                        "auth": subscription["auth"],
                    },
                },
                data=json.dumps(payload, ensure_ascii=False),
                vapid_private_key=self.private_key,
                vapid_claims={"sub": self.subject},
                ttl=self.ttl_seconds,
            )
        except WebPushException as exc:
            response = getattr(exc, "response", None)
            status_code = int(getattr(response, "status_code", 0) or 0)
            permanent = status_code in {404, 410}
            detail = f"Web Push delivery failed ({status_code or 'unknown'}): {exc}"
            raise NotificationDeliveryError(detail, permanent=permanent) from exc


class BrowserSubscription(BaseModel):
    endpoint: str = Field(min_length=1, max_length=4096)
    expirationTime: float | None = None
    keys: dict[str, str]
    contentEncoding: str | None = None


class SubscriptionDelete(BaseModel):
    endpoint: str = Field(min_length=1, max_length=4096)


class PreferenceUpdate(BaseModel):
    preferences: dict[str, bool]


class TestNotificationRequest(BaseModel):
    title: str = Field(default="PETIT テスト通知", min_length=1, max_length=120)
    body: str = Field(default="バックグラウンド通知を受信できました。", min_length=1, max_length=500)
    url: str = Field(default="/", min_length=1, max_length=2048)


def init_db() -> None:
    """Create notification tables without coupling them to PETIT's core schema."""
    with db.get_connection() as conn:
        conn.executescript(_NOTIFICATION_SCHEMA)
        now = db.now_iso()
        for category in CATEGORY_LABELS:
            conn.execute(
                "INSERT OR IGNORE INTO notification_preferences(owner_id, category, enabled, updated_at) "
                "VALUES (?, ?, 0, ?)",
                (_owner_id(), category, now),
            )


def _owner_id() -> str:
    return str(getattr(config, "PETIT_OWNER_ID", "soso") or "soso")


def _vapid_public_key() -> str:
    return os.getenv("PETIT_VAPID_PUBLIC_KEY", "").strip()


def _vapid_private_key() -> str:
    return os.getenv("PETIT_VAPID_PRIVATE_KEY", "").strip()


def _vapid_subject() -> str:
    return os.getenv("PETIT_VAPID_SUBJECT", "").strip()


def _ttl_seconds() -> int:
    raw = os.getenv("PETIT_WEB_PUSH_TTL_SECONDS", "300").strip()
    try:
        return max(0, min(int(raw), 86400))
    except ValueError:
        return 300


def web_push_configured() -> bool:
    return bool(_vapid_public_key() and _vapid_private_key() and _vapid_subject())


def dependency_available() -> bool:
    return importlib.util.find_spec("pywebpush") is not None


def notification_status() -> dict[str, Any]:
    init_db()
    with db.get_connection() as conn:
        active = int(
            conn.execute(
                "SELECT COUNT(*) FROM push_subscriptions WHERE provider='web_push' AND disabled_at IS NULL"
            ).fetchone()[0]
        )
    return {
        "supported": True,
        "provider": "web_push",
        "configured": web_push_configured(),
        "dependency_available": dependency_available(),
        "public_key": _vapid_public_key(),
        "active_subscriptions": active,
        "preferences": get_preferences(),
        "categories": [
            {"id": category, "label": label}
            for category, label in CATEGORY_LABELS.items()
        ],
    }


def get_preferences() -> dict[str, bool]:
    init_db()
    result = dict(DEFAULT_PREFERENCES)
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT category, enabled FROM notification_preferences WHERE owner_id = ?",
            (_owner_id(),),
        ).fetchall()
    for row in rows:
        if row["category"] in result:
            result[row["category"]] = bool(row["enabled"])
    return result


def update_preferences(values: dict[str, bool]) -> dict[str, bool]:
    unknown = sorted(set(values) - set(CATEGORY_LABELS))
    if unknown:
        raise ValueError(f"Unknown notification categories: {', '.join(unknown)}")
    init_db()
    now = db.now_iso()
    with db.get_connection() as conn:
        for category, enabled in values.items():
            conn.execute(
                "INSERT INTO notification_preferences(owner_id, category, enabled, updated_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(owner_id, category) DO UPDATE SET "
                "enabled=excluded.enabled, updated_at=excluded.updated_at",
                (_owner_id(), category, int(bool(enabled)), now),
            )
    return get_preferences()


def upsert_subscription(payload: BrowserSubscription, user_agent: str | None = None) -> dict[str, Any]:
    endpoint = payload.endpoint.strip()
    p256dh = str(payload.keys.get("p256dh") or "").strip()
    auth = str(payload.keys.get("auth") or "").strip()
    if not endpoint.startswith("https://"):
        raise ValueError("Push subscription endpoint must use HTTPS")
    if not p256dh or not auth:
        raise ValueError("Push subscription keys.p256dh and keys.auth are required")
    init_db()
    now = db.now_iso()
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO push_subscriptions(provider, endpoint, p256dh, auth, content_encoding, user_agent, created_at, updated_at, disabled_at) "
            "VALUES ('web_push', ?, ?, ?, ?, ?, ?, ?, NULL) "
            "ON CONFLICT(endpoint) DO UPDATE SET "
            "p256dh=excluded.p256dh, auth=excluded.auth, content_encoding=excluded.content_encoding, "
            "user_agent=excluded.user_agent, updated_at=excluded.updated_at, disabled_at=NULL",
            (
                endpoint,
                p256dh,
                auth,
                (payload.contentEncoding or "aes128gcm").strip() or "aes128gcm",
                (user_agent or "")[:1000] or None,
                now,
                now,
            ),
        )
        row = conn.execute(
            "SELECT id, provider, endpoint, created_at, updated_at, disabled_at "
            "FROM push_subscriptions WHERE endpoint = ?",
            (endpoint,),
        ).fetchone()
    return dict(row)


def disable_subscription(endpoint: str) -> bool:
    init_db()
    now = db.now_iso()
    with db.get_connection() as conn:
        cur = conn.execute(
            "UPDATE push_subscriptions SET disabled_at=?, updated_at=? "
            "WHERE endpoint=? AND disabled_at IS NULL",
            (now, now, endpoint.strip()),
        )
        return cur.rowcount > 0


def active_subscriptions() -> list[dict[str, Any]]:
    init_db()
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT id, provider, endpoint, p256dh, auth, content_encoding, user_agent, created_at, updated_at "
            "FROM push_subscriptions WHERE provider='web_push' AND disabled_at IS NULL ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]


def _provider() -> NotificationProvider:
    if not web_push_configured():
        raise NotificationDeliveryError(
            "Web Push is not configured. Set PETIT_VAPID_PUBLIC_KEY, PETIT_VAPID_PRIVATE_KEY, and PETIT_VAPID_SUBJECT."
        )
    return WebPushProvider(
        private_key=_vapid_private_key(),
        subject=_vapid_subject(),
        ttl_seconds=_ttl_seconds(),
    )


def _create_event(category: str, title: str, body: str, url: str) -> tuple[int, dict[str, Any]]:
    payload = {
        "title": title,
        "body": body,
        "url": url or "/",
        "category": category,
        "tag": f"petit-{category}",
        "icon": "/static/icon-192.png",
        "badge": "/static/favicon-64.png",
    }
    now = db.now_iso()
    with db.get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO notification_events(category, title, body, target_url, payload_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (category, title, body, payload["url"], json.dumps(payload, ensure_ascii=False), now),
        )
        return int(cur.lastrowid), payload


def _record_delivery(
    *,
    event_id: int,
    provider: str,
    status: str,
    subscription_id: int | None = None,
    error: str | None = None,
) -> None:
    now = db.now_iso()
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO notification_deliveries(event_id, provider, subscription_id, status, error, created_at, sent_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                event_id,
                provider,
                subscription_id,
                status,
                error,
                now,
                now if status == "sent" else None,
            ),
        )


def dispatch_notification(
    *,
    category: str,
    title: str,
    body: str,
    url: str = "/",
    respect_preferences: bool = True,
    provider: NotificationProvider | None = None,
) -> dict[str, Any]:
    """Create one event and deliver it through the configured provider.

    Callers that schedule reminders should leave ``respect_preferences=True``.
    The explicit test endpoint bypasses preferences because it is user-triggered.
    """
    if category not in CATEGORY_LABELS and category != "test":
        raise ValueError(f"Unknown notification category: {category}")
    title = title.strip()
    body = body.strip()
    if not title or not body:
        raise ValueError("Notification title and body are required")

    init_db()
    event_id, payload = _create_event(category, title[:120], body[:500], url[:2048] or "/")

    if respect_preferences and not get_preferences().get(category, False):
        _record_delivery(event_id=event_id, provider="none", status="skipped_disabled")
        return {
            "event_id": event_id,
            "status": "skipped_disabled",
            "sent": 0,
            "failed": 0,
            "disabled": 0,
        }

    subscriptions = active_subscriptions()
    if not subscriptions:
        _record_delivery(event_id=event_id, provider="web_push", status="skipped_no_subscription")
        return {
            "event_id": event_id,
            "status": "skipped_no_subscription",
            "sent": 0,
            "failed": 0,
            "disabled": 0,
        }

    active_provider = provider or _provider()
    sent = 0
    failed = 0
    disabled = 0
    errors: list[str] = []
    for subscription in subscriptions:
        try:
            active_provider.send(subscription, payload)
        except NotificationDeliveryError as exc:
            failed += 1
            if exc.permanent and disable_subscription(subscription["endpoint"]):
                disabled += 1
            errors.append(str(exc))
            _record_delivery(
                event_id=event_id,
                provider=active_provider.name,
                subscription_id=int(subscription["id"]),
                status="failed_permanent" if exc.permanent else "failed",
                error=str(exc)[:2000],
            )
        except Exception as exc:  # noqa: BLE001
            failed += 1
            errors.append(f"{type(exc).__name__}: {exc}")
            _record_delivery(
                event_id=event_id,
                provider=active_provider.name,
                subscription_id=int(subscription["id"]),
                status="failed",
                error=f"{type(exc).__name__}: {exc}"[:2000],
            )
        else:
            sent += 1
            _record_delivery(
                event_id=event_id,
                provider=active_provider.name,
                subscription_id=int(subscription["id"]),
                status="sent",
            )

    status = "sent" if sent and not failed else ("partial" if sent else "failed")
    return {
        "event_id": event_id,
        "status": status,
        "sent": sent,
        "failed": failed,
        "disabled": disabled,
        "errors": errors[:3],
    }


@router.get("/status")
def get_notification_status() -> dict[str, Any]:
    return notification_status()


@router.get("/preferences")
def get_notification_preferences() -> dict[str, Any]:
    return {"preferences": get_preferences(), "categories": CATEGORY_LABELS}


@router.put("/preferences")
def put_notification_preferences(payload: PreferenceUpdate) -> JSONResponse:
    try:
        preferences = update_preferences(payload.preferences)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"preferences": preferences})


@router.post("/subscriptions")
def register_notification_subscription(payload: BrowserSubscription, request: Request) -> JSONResponse:
    try:
        subscription = upsert_subscription(payload, user_agent=request.headers.get("user-agent"))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"registered": True, "subscription": subscription})


@router.delete("/subscriptions")
def unregister_notification_subscription(payload: SubscriptionDelete) -> dict[str, Any]:
    return {"removed": disable_subscription(payload.endpoint)}


@router.post("/test")
def send_test_notification(payload: TestNotificationRequest) -> JSONResponse:
    try:
        result = dispatch_notification(
            category="test",
            title=payload.title,
            body=payload.body,
            url=payload.url,
            respect_preferences=False,
        )
    except NotificationDeliveryError as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    status_code = 200 if result["sent"] else 503
    return JSONResponse(result, status_code=status_code)
